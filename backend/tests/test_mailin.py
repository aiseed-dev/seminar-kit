"""受信処理(mailin)の判別・抽出と定型文の検査(IMAP/SMTP/DB なし)。"""

import email
import email.policy
import uuid
from datetime import datetime
from email.message import EmailMessage

from app.models import Application, Company, Course
from app.services import mail, mailin
from app.services.forms import JST

# ---- テスト用の部品 ----


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, *, reply_to=None):
        self.sent.append((to, subject, body, reply_to))


class StubSession:
    """companies 照会が None を返すだけの代役((c)経路の検査用)。"""

    def scalar(self, stmt):
        return None


def make_msg(sender="taro@example.jp", body="こんにちは", xlsx: bytes | None = None):
    msg = EmailMessage()
    msg["From"] = f"徳島 太郎 <{sender}>"
    msg["To"] = "moshikomi@example.jp"
    msg["Subject"] = "申込"
    msg["Message-ID"] = "<test-1@example.jp>"
    msg.set_content(body)
    if xlsx is not None:
        msg.add_attachment(
            xlsx,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="申込様式.xlsx",
        )
    return msg


def reparse(msg: EmailMessage) -> EmailMessage:
    return email.message_from_bytes(msg.as_bytes(), policy=email.policy.default)


# ---- 判別 ----


def test_first_xlsx():
    msg = reparse(make_msg(xlsx=b"dummy-xlsx"))
    assert mailin.first_xlsx(msg) == b"dummy-xlsx"


def test_first_xlsx_none():
    msg = reparse(make_msg())
    assert mailin.first_xlsx(msg) is None
    assert "こんにちは" in mailin.body_text(msg)


def test_unknown_sender_without_form_gets_guidance(tmp_path):
    """(c) 添付なし+未登録 → 定型返信+pending。"""
    mailer = FakeMailer()
    raw = make_msg(body="申し込みたいです").as_bytes()
    got = mailin.handle(StubSession(), mailer, raw, tmp_path)
    assert got == mailin.PENDING
    ((to, subject, _, reply_to),) = mailer.sent
    assert to == "taro@example.jp"
    assert "様式" in subject
    assert reply_to == "<test-1@example.jp>"


def test_broken_form_gets_fix_request(tmp_path):
    """(a) xlsx が様式でない → 修正依頼+pending(DB に触る前に弾ける)。"""
    mailer = FakeMailer()
    raw = make_msg(xlsx=b"not-a-real-xlsx").as_bytes()
    got = mailin.handle(StubSession(), mailer, raw, tmp_path)
    assert got == mailin.PENDING
    ((_, subject, body, _),) = mailer.sent
    assert "確認" in subject


# ---- 経路3の抽出 ----


def test_extract_entrants_variants():
    body = """お世話になっております。
DX入門セミナーに以下の2名で申し込みます。

山田太郎(会場)
・鈴木 花子 オンライン

よろしくお願いします。"""
    assert mailin.extract_entrants(body) == [
        ("山田太郎", "venue"),
        ("鈴木 花子", "online"),
    ]


def test_extract_entrants_zoom_and_satellite():
    body = "田中一郎 ZOOM\n佐藤次郎(サテライト)"
    assert mailin.extract_entrants(body) == [
        ("田中一郎", "online"),
        ("佐藤次郎", "satellite"),
    ]


def test_extract_entrants_rejects_noise():
    body = """参加場所:会場
会場までの道順を教えてください
オンラインの参加方法がわかりません
会場
"""
    assert mailin.extract_entrants(body) == []


def test_find_course_longest_match():
    a = Course(id=uuid.uuid4(), title="DX入門")
    b = Course(id=uuid.uuid4(), title="DX入門セミナー")
    got = mailin.find_course("「DX入門セミナー」に申し込みます", [a, b])
    assert got is b


def test_find_course_no_match():
    a = Course(id=uuid.uuid4(), title="労務管理講座")
    assert mailin.find_course("DXの件", [a]) is None


def test_quick_form_snapshot():
    company = Company(
        company_name="株式会社テスト",
        company_kana="カブシキガイシャテスト",
        contact_name="徳島 太郎",
        contact_kana="トクシマ タロウ",
        contact_email="taro@example.jp",
        postal_code="770-0000",
        address="徳島市",
        tel="088-000-0000",
        fax=None,
    )
    course = Course(id=uuid.uuid4(), title="DX入門セミナー")
    form = mailin.quick_form(company, course, [("山田太郎", "venue")])
    assert form.course_id == course.id
    assert form.company_name == "株式会社テスト"
    (e,) = form.entrants
    assert (e.name, e.loc, e.email) == ("山田太郎", "venue", "taro@example.jp")
    assert e.kana == ""  # 簡易メールではフリガナを求めない


def test_appno_pattern():
    assert mailin.APP_NO_RE.search("申込番号 2026-00042 の件").group(1) == "2026-00042"
    assert mailin.APP_NO_RE.search("申込番号 2026-DX-3 の件").group(1) == "2026-DX-3"
    assert mailin.APP_NO_RE.search("TEL 088-1234") is None


# ---- 定型文 ----


def make_application() -> Application:
    return Application(
        application_no="2026-00042",
        contact_name="徳島 太郎",
        company_name="株式会社テスト",
    )


def make_course() -> Course:
    return Course(
        id=uuid.uuid4(),
        title="DX入門セミナー",
        starts_at=datetime(2026, 9, 1, 13, 30, tzinfo=JST),
    )


def test_receipt_mail():
    from app.services.parse import Entrant

    entrants = (
        Entrant(name="山田太郎", kana="", role="", email="a@b.jp", loc="venue"),
    )
    subject, body = mail.receipt(make_application(), make_course(), entrants)
    assert "2026-00042" in subject
    assert "DX入門セミナー" in subject
    assert "山田太郎(会場)" in body
    assert "返信" in body  # キャンセルは返信で
    assert "受講者名" in body  # 次回は簡易メールでOKの案内


def test_fix_request_mail():
    subject, body = mail.fix_request(["「企業・団体名」が未記入です"])
    assert "・「企業・団体名」が未記入です" in body
    assert "事務局" in body  # 誤判定でも人が確認する旨


def test_send_bulk():
    mailer = FakeMailer()
    n = mail.send_bulk(mailer, ["a@x.jp", "b@x.jp"], "件名", "本文", interval_sec=0)
    assert n == 2
    assert [s[0] for s in mailer.sent] == ["a@x.jp", "b@x.jp"]

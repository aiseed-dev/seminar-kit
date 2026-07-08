"""実 PostgreSQL での一気通貫テスト(組み込み pgserver / TEST_DB_URL)。

経路2(様式添付)→ 経路3(簡易メール)の順で、登録・採番・事前登録・
受領メールまでを通しで確かめる。
"""

import io
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage

import pytest
from app.models import Application, Attendee, Base, Category, Company, Course
from app.services import forms, mailin
from openpyxl import load_workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.db

NOW = datetime(2026, 8, 1, 10, 0, tzinfo=forms.JST)
SENDER = "taro@e2e.example.jp"


@pytest.fixture(scope="module")
def engine(test_db_url):
    eng = create_engine(test_db_url)
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS seminar")
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(scope="module")
def course_id(engine):
    with Session(engine) as s:
        cat = Category(slug="dx", name="デジタル化・DX")
        s.add(cat)
        s.flush()
        course = Course(
            id=uuid.uuid4(),
            title="DX入門セミナー",
            category_id=cat.id,
            status="open",
            starts_at=NOW + timedelta(days=30),
            apply_deadline=NOW + timedelta(days=20),
            allow_venue=True,
            allow_online=True,
            capacity_venue=30,
        )
        s.add(course)
        s.commit()
        return course.id


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, *, reply_to=None):
        self.sent.append((to, subject, body))


def filled_form(course: Course) -> bytes:
    buf = io.BytesIO()
    forms.build(course, "moshikomi@example.jp").save(buf)
    buf.seek(0)
    wb = load_workbook(buf)

    def put(name, value):
        ((title, coord),) = wb.defined_names[name].destinations
        wb[title][coord] = value

    put("company_kana", "カブシキガイシャイーツーイー")
    put("company_name", "株式会社E2E")
    put("postal_code", "770-0000")
    put("address", "徳島市")
    put("tel", "088-000-0000")
    put("contact_kana", "トクシマ タロウ")
    put("contact_name", "徳島 太郎")
    put("contact_email", SENDER)
    put("att1_name", "山田 太郎")
    put("att1_kana", "ヤマダ タロウ")
    put("att1_role", "総務部")
    put("att1_email", "yamada@e2e.example.jp")
    put("att1_loc", "会場")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def as_mail(body: str, xlsx: bytes | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"徳島 太郎 <{SENDER}>"
    msg["To"] = "moshikomi@example.jp"
    msg["Subject"] = "申込"
    msg["Message-ID"] = "<e2e@example.jp>"
    msg.set_content(body)
    if xlsx is not None:
        msg.add_attachment(
            xlsx,
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="申込様式.xlsx",
        )
    return msg.as_bytes()


def test_route2_form_mail(engine, course_id, tmp_path):
    mailer = FakeMailer()
    with Session(engine) as s:
        course = s.get(Course, course_id)
        raw = as_mail("よろしくお願いします", filled_form(course))
        got = mailin.handle(s, mailer, raw, tmp_path)
        s.commit()
    assert got == mailin.DONE

    with Session(engine) as s:
        app_row = s.scalar(select(Application))
        assert app_row.application_no.endswith("-00001")
        assert app_row.source == "mail"
        assert app_row.received_file and app_row.received_file.endswith(".xlsx")
        company = s.scalar(select(Company))
        assert company.contact_email == SENDER  # 事前登録された
        assert app_row.company_id == company.id
        (att,) = s.scalars(select(Attendee)).all()
        assert (att.name, att.location) == ("山田 太郎", "venue")
    ((to, subject, body),) = mailer.sent
    assert to == SENDER and "-00001" in subject


def test_route3_quick_mail(engine, course_id, tmp_path):
    mailer = FakeMailer()
    raw = as_mail("DX入門セミナー\n鈴木 花子(オンライン)")
    with Session(engine) as s:
        got = mailin.handle(s, mailer, raw, tmp_path)
        s.commit()
    assert got == mailin.DONE

    with Session(engine) as s:
        quick = s.scalar(select(Application).where(Application.source == "quick"))
        assert quick.application_no.endswith("-00002")  # 通し連番
        assert quick.company_name == "株式会社E2E"  # 事前登録から補完
        atts = s.scalars(
            select(Attendee).where(Attendee.application_id == quick.id)
        ).all()
        assert [(a.name, a.location) for a in atts] == [("鈴木 花子", "online")]
    assert len(mailer.sent) == 1  # 受領メール


def test_route2_text_mail(engine, course_id, tmp_path):
    """(a') 本文の送信用テキスト(マクロ生成形式)でも登録できる。"""
    mailer = FakeMailer()
    body = "\n".join(
        [
            f"講座ID: {course_id}",
            "様式版: 1",
            "企業名フリガナ: カブシキガイシャホンブン",
            "企業名: 株式会社本文",
            "郵便番号: 770-0001",
            "所在地: 徳島市",
            "電話番号: 088-111-1111",
            "担当者フリガナ: ホンブン タロウ",
            "担当者名: 本文 太郎",
            "メールアドレス: text@e2e.example.jp",
            "受講者1: 貼付 花子",
            "受講者1フリガナ: チョウフ ハナコ",
            "受講者1所属: 企画部",
            "受講者1メール: hanako@e2e.example.jp",
            "受講者1参加場所: オンライン",
        ]
    )
    msg = EmailMessage()
    msg["From"] = "本文 太郎 <text@e2e.example.jp>"
    msg["To"] = "moshikomi@example.jp"
    msg["Subject"] = "申込(本文)"
    msg.set_content(body)

    with Session(engine) as s:
        got = mailin.handle(s, mailer, msg.as_bytes(), tmp_path)
        s.commit()
    assert got == mailin.DONE

    with Session(engine) as s:
        app_row = s.scalar(
            select(Application).where(Application.company_name == "株式会社本文")
        )
        assert app_row.source == "mail"
        assert app_row.application_no.endswith("-00003")  # 通し連番の続き
        assert app_row.received_file.endswith(".eml")
    ((to, subject, _),) = mailer.sent
    assert to == "text@e2e.example.jp" and "【受付】" in subject


def test_next_no_fy_cat_on_real_db(engine, course_id):
    """fy-cat 方式の LIKE 絞り込みが実 DB で正しく働くこと。

    既存2件は seq 方式(2026-0000n)で登録済み → prefix 不一致なので
    fy-cat の連番は 1 から始まる。
    """
    from app.services import no

    with Session(engine) as s:
        got = no.next_no(s, NOW, code="dx", style="fy-cat")
    assert got == ("2026-DX-1", 2026, 1)


def test_unreadable_quick_mail_goes_pending(engine, course_id, tmp_path):
    mailer = FakeMailer()
    raw = as_mail("先日の件、ありがとうございました。")
    with Session(engine) as s:
        got = mailin.handle(s, mailer, raw, tmp_path)
        s.commit()
    assert got == mailin.PENDING
    assert mailer.sent == []  # 登録済み企業には自動返信しない(事務局が対応)

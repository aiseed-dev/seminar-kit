"""申込受信箱の処理(経路2: 様式 xlsx 添付/経路3: 簡易メール)。

申込専用アドレスの INBOX を IMAP でポーリングし、1通ずつ処理して
フォルダへ移動する。**状態=所在フォルダ**(INBOX=未着手 → done=処理済み /
pending=未処理)。pending は事務局アプリの「未処理受信」画面が一覧する。
機械で裁けないものは必ず pending に落とす(黙って捨てない)。

判別:
  (a) xlsx 添付あり → 経路2。parse(発行キー検証込み)→ regist(source='mail')
  (b) 添付なし+送信者が companies に登録済み → 経路3。本文から
      講座(講座名または申込番号)と「受講者名+参加場所」の行を読む。
      確実に読めるものだけ登録し(source='quick')、読めなければ
      自動返信なしで pending へ(登録済み企業は事務局が電話一本で補完)
  (c) 添付なし+未登録の送信者 → **自動返信せず** pending へ。
      宛先は非公開のため通常は届かない=届くのはスパムか人づての
      正規メール。ボットへの逆流(バックスキャッター)を防ぎ、
      判断は人に任せる
"""

import email
import email.policy
import imaplib
import logging
import re
import time
from collections.abc import Iterable
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Company, Course
from app.services import forms, mail, parse, regist
from app.services.parse import Entrant, FormData

log = logging.getLogger(__name__)

DONE = "done"
PENDING = "pending"

# ---- 判別・抽出(純粋なロジック。テストはここを厚く) ----


def body_text(msg: EmailMessage) -> str:
    """本文のプレーンテキストを取り出す。"""
    part = msg.get_body(preferencelist=("plain",))
    if part is None:
        return ""
    return part.get_content()


def first_xlsx(msg: EmailMessage) -> bytes | None:
    """最初の xlsx 添付(なければ None)。"""
    for part in msg.iter_attachments():
        name = part.get_filename() or ""
        if name.lower().endswith(".xlsx"):
            return part.get_payload(decode=True)
    return None


def find_course(body: str, courses: Iterable[Course]) -> Course | None:
    """本文に講座名が含まれる講座(最長一致)。"""
    hits = [c for c in courses if c.title and c.title in body]
    return max(hits, key=lambda c: len(c.title), default=None)


# 申込番号(2026-00042 / 2026-DX-3)。素の数字は4桁以上(電話番号と区別)
APP_NO_RE = re.compile(r"\b(20\d{2}-(?:[A-Za-z0-9]{1,8}-\d{1,4}|\d{4,}))\b")

# 受講者行と見なさない語(問い合わせ文などを弾く)
_STOP = (
    "参加",
    "受講",
    "講座",
    "申込",
    "様式",
    "案内",
    "方法",
    "ください",
    "お願い",
    "よろしく",
    "です",
    "ます",
    "ません",
    "ない",
    "まで",
    "から",
)
_SEP_RE = re.compile(r"[・:::()()【】\[\]「」<>\-=*　]+")
_NAME_RE = re.compile(r"^[一-龯ぁ-んァ-ヶーA-Za-z][一-龯ぁ-んァ-ヶー々A-Za-z\s]{1,15}$")


def extract_entrants(body: str) -> list[tuple[str, str]]:
    """「氏名+参加場所」の行を拾う。確実に読めるものだけ返す。

    書式は自由(例: 「山田太郎(会場)」「・鈴木花子 オンライン」)。
    参加場所のことばを含む行から氏名らしき部分を取り出し、
    氏名として不自然な行は捨てる(拾い漏れは pending → 事務局が補完)。
    """
    labels = [
        (forms.LOC_SATELLITE, "satellite"),
        (forms.LOC_ONLINE, "online"),
        ("ZOOM", "online"),
        ("Zoom", "online"),
        ("zoom", "online"),
        (forms.LOC_VENUE, "venue"),
    ]
    out: list[tuple[str, str]] = []
    for line in body.splitlines():
        s = line.strip()
        if not s or len(s) > 40:
            continue
        loc = next((code for label, code in labels if label in s), None)
        if loc is None:
            continue
        name = s
        for label, _ in labels:
            name = name.replace(label, " ")
        name = _SEP_RE.sub(" ", name).strip()
        name = re.sub(r"\s+", " ", name)
        if not name or any(w in name for w in _STOP):
            continue
        if not _NAME_RE.match(name):
            continue
        out.append((name, loc))
    return out


def quick_form(
    company: Company, course: Course, entrants: list[tuple[str, str]]
) -> FormData:
    """経路3: 事前登録情報+本文の受講者から FormData を組み立てる。

    フリガナ・役職は簡易メールでは求めない(空)。接続情報の送付先は
    担当者アドレスとする。
    """
    return FormData(
        course_id=course.id,
        form_ver=forms.FORM_VER,
        company_name=company.company_name,
        company_kana=company.company_kana,
        contact_name=company.contact_name,
        contact_kana=company.contact_kana,
        contact_email=company.contact_email,
        postal_code=company.postal_code,
        address=company.address,
        tel=company.tel,
        fax=company.fax,
        entrants=tuple(
            Entrant(name=name, kana="", role="", email=company.contact_email, loc=loc)
            for name, loc in entrants
        ),
    )


# ---- 1通の処理(DB・送信を伴う) ----


def _save_original(received_dir: str | Path, application, data: bytes, ext: str):
    """原本(監査証跡)を申込番号の名前で保存し、申込に紐付ける。"""
    d = Path(received_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{application.application_no}{ext}"
    path.write_bytes(data)
    application.received_file = str(path)


def _course_from_body(session: Session, body: str) -> Course | None:
    """本文から講座を特定(申込番号 → 講座名の順に試す)。"""
    m = APP_NO_RE.search(body)
    if m:
        prev = session.scalar(
            select(Application).where(Application.application_no == m.group(1))
        )
        if prev is not None:
            return session.get(Course, prev.course_id)
    open_courses = session.scalars(select(Course).where(Course.status == "open")).all()
    return find_course(body, open_courses)


def handle(
    session: Session,
    mailer: mail.Mailer,
    raw: bytes,
    received_dir: str | Path,
    secret: str = "",
) -> str:
    """メール1通を処理し、移動先(DONE / PENDING)を返す。"""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    sender = parseaddr(msg.get("From", ""))[1].lower()
    msgid = msg.get("Message-ID")
    if not sender:
        return PENDING

    xlsx = first_xlsx(msg)
    if xlsx is not None:  # 経路2: 様式添付
        try:
            form = parse.parse(xlsx, secret=secret)
            application = regist.regist(session, form, source="mail")
        except (parse.Invalid, regist.Rejected) as e:
            subject, text = mail.fix_request(e.issues)
            mailer.send(sender, subject, text, reply_to=msgid)
            return PENDING
        _save_original(received_dir, application, xlsx, ".xlsx")
        session.flush()
        course = session.get(Course, form.course_id)
        subject, text = mail.receipt(application, course, form.entrants)
        mailer.send(sender, subject, text, reply_to=msgid)
        return DONE

    company = session.scalar(select(Company).where(Company.contact_email == sender))
    if company is None:  # (c) 未登録+添付なし → 自動返信しない(逆流防止)
        return PENDING

    # 経路3: 簡易メール(事前登録済み)
    body = body_text(msg)
    course = _course_from_body(session, body)
    entrants = extract_entrants(body)
    if course is None or not entrants:
        return PENDING  # 自動返信なし(事務局が原文を見て補完・連絡)
    form = quick_form(company, course, entrants)
    try:
        application = regist.regist(session, form, source="quick")
    except regist.Rejected as e:
        subject, text = mail.fix_request(e.issues)
        mailer.send(sender, subject, text, reply_to=msgid)
        return PENDING
    _save_original(received_dir, application, raw, ".eml")
    session.flush()
    subject, text = mail.receipt(application, course, form.entrants)
    mailer.send(sender, subject, text, reply_to=msgid)
    return DONE


# ---- IMAP(受信箱=キュー) ----


class ImapBox:
    """申込受信箱。フォルダ=キューの状態(事務局アプリの未処理一覧も使う)。"""

    def __init__(self, cfg=None):
        if cfg is None:
            from app.core.config import get_settings

            cfg = get_settings()
        self.cfg = cfg
        self.conn = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
        self.conn.login(cfg.imap_user, cfg.imap_pass)
        for folder in (cfg.imap_done, cfg.imap_pending, cfg.imap_returned):
            self.conn.create(folder)  # 既存なら NO が返るだけ
        self.select()

    def select(self, folder: str = "INBOX") -> None:
        self.conn.select(folder)

    def fetch_all(self) -> list[tuple[bytes, bytes]]:
        """選択中フォルダの全メールを (uid, 原文) で返す。"""
        _, data = self.conn.uid("search", None, "ALL")
        out = []
        for uid in data[0].split():
            _, fetched = self.conn.uid("fetch", uid, "(RFC822)")
            if fetched and fetched[0]:
                out.append((uid, fetched[0][1]))
        return out

    def fetch_new(self) -> list[tuple[bytes, bytes]]:
        """INBOX の全メールを (uid, 原文) で返す(ポーリング用)。"""
        self.select()
        return self.fetch_all()

    def move(self, uid: bytes, folder: str) -> None:
        """選択中フォルダから folder へ移す。"""
        self.conn.uid("copy", uid, folder)
        self.conn.uid("store", uid, "+FLAGS", r"(\Deleted)")
        self.conn.expunge()

    def append(self, folder: str, raw: bytes) -> None:
        """メールを folder に直接投函する(経路1の不備分の合流用)。"""
        self.conn.append(folder, None, None, raw)

    def close(self) -> None:
        self.conn.logout()


def poll_once(box, session_factory, mailer: mail.Mailer, received_dir) -> dict:
    """受信箱を1回さらう。1通=1トランザクション。想定外の失敗も pending へ。"""
    counts = {DONE: 0, PENDING: 0}
    for uid, raw in box.fetch_new():
        session: Session = session_factory()
        try:
            disposition = handle(
                session, mailer, raw, received_dir, secret=box.cfg.form_secret
            )
            session.commit()
        except Exception:
            log.exception("申込メールの処理に失敗(uid=%s)。未処理へ移動", uid)
            session.rollback()
            disposition = PENDING
        finally:
            session.close()
        cfg = box.cfg
        box.move(uid, cfg.imap_done if disposition == DONE else cfg.imap_pending)
        counts[disposition] += 1
    return counts


def main() -> None:
    """ポーリング常駐(systemd で動かす)。`--once` で1回だけさらって終了。"""
    import sys

    from app.core.config import get_settings
    from app.core.db import get_sessionmaker

    logging.basicConfig(level=logging.INFO)
    once = "--once" in sys.argv
    cfg = get_settings()
    mailer = mail.Smtp(cfg)
    while True:
        box = ImapBox(cfg)
        try:
            counts = poll_once(box, get_sessionmaker(), mailer, cfg.received_dir)
            if counts[DONE] or counts[PENDING]:
                log.info("処理 %s / 未処理 %s", counts[DONE], counts[PENDING])
        finally:
            box.close()
        if once:
            break
        time.sleep(cfg.imap_poll_sec)


if __name__ == "__main__":
    main()

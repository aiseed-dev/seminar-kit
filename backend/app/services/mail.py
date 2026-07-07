"""メール送信(送信手段の抽象化)と定型文。

送信はすべてこのモジュールを通す。段階1は機関の既存 SMTP リレー、
段階2で自営メールサーバー(Stalwart)へ——接続先の変更は設定だけで済む。
一斉送信は連続投函せず間隔を空ける(先方サーバーの受信制限対策)。
"""

import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol

from app.models import Application, Course
from app.services.forms import LOC_JA, jst
from app.services.parse import Entrant


class Mailer(Protocol):
    """送信手段の差し替え点(本番 SMTP / テストはフェイク)。"""

    def send(
        self, to: str, subject: str, body: str, *, reply_to: str | None = None
    ) -> None: ...


class Smtp:
    """機関の SMTP リレーで送る(設定は core.config)。"""

    def __init__(self, cfg=None):
        if cfg is None:
            from app.core.config import get_settings

            cfg = get_settings()
        self.cfg = cfg

    def send(
        self, to: str, subject: str, body: str, *, reply_to: str | None = None
    ) -> None:
        cfg = self.cfg
        msg = EmailMessage()
        msg["From"] = formataddr((cfg.mail_from_name, cfg.submit_addr))
        msg["To"] = to
        msg["Subject"] = subject
        if reply_to:
            msg["In-Reply-To"] = reply_to
            msg["References"] = reply_to
        msg.set_content(body)
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as smtp:
            if cfg.smtp_starttls:
                smtp.starttls()
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, cfg.smtp_pass)
            smtp.send_message(msg)


def get_mailer() -> Mailer:
    """FastAPI 依存(テストではフェイクに差し替える)。"""
    return Smtp()


def send_bulk(
    mailer: Mailer,
    recipients: list[str],
    subject: str,
    body: str,
    interval_sec: float = 1.0,
) -> int:
    """一斉送信(1通ずつ・間隔を空ける)。送信数を返す。"""
    for i, to in enumerate(recipients):
        if i:
            time.sleep(interval_sec)
        mailer.send(to, subject, body)
    return len(recipients)


# ---- 定型文(自動返信)。すべて (件名, 本文) を返す ----


def receipt(
    application: Application, course: Course, entrants: tuple[Entrant, ...]
) -> tuple[str, str]:
    """受領メール(申込番号つき)。"""
    names = "\n".join(f"  {e.name}({LOC_JA[e.loc]})" for e in entrants)
    subject = f"【受付】{course.title}(申込番号 {application.application_no})"
    body = f"""{application.contact_name} 様

お申し込みを受け付けました。

申込番号: {application.application_no}
講座名: {course.title}
開催日時: {jst(course.starts_at)}
受講者:
{names}

・内容の変更・キャンセルは、このメールへの返信でご依頼ください。
・次回からは、このメールアドレスから「講座名・受講者名・参加場所」だけの
  メールでお申し込みいただけます(住所等の記入は不要です)。

{application.company_name} 御中
"""
    return subject, body


def fix_request(issues: list[str]) -> tuple[str, str]:
    """読み取れない・不備の申込への修正依頼(原文は未処理フォルダへ)。"""
    lines = "\n".join(f"・{s}" for s in issues)
    subject = "【要確認】お申し込み内容について"
    body = f"""お申し込みのメールを受け取りましたが、以下の点が確認できませんでした。

{lines}

お手数ですが、内容をご確認のうえ再送をお願いいたします。
このご案内に心当たりがない場合は、そのままお待ちください。
事務局が内容を確認してご連絡いたします。
"""
    return subject, body


def cancelled(application: Application, course: Course) -> tuple[str, str]:
    """キャンセル受付(事務局操作で送る)。"""
    subject = f"【キャンセル受付】{course.title}(申込番号 {application.application_no})"
    body = f"""{application.contact_name} 様

下記のお申し込みのキャンセルを承りました。

申込番号: {application.application_no}
講座名: {course.title}
開催日時: {jst(course.starts_at)}

またのご参加をお待ちしております。

{application.company_name} 御中
"""
    return subject, body


# 添付なし・未登録の送信者への自動返信は行わない(2026-07-08 決定)。
# 宛先は非公開のため通常は届かない——届くのはスパムか人づての正規メールで、
# 前者への自動返信はバックスキャッターになる。未処理フォルダで人が判断する。

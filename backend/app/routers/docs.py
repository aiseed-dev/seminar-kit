"""経路1: OnlyOffice Docs(Document Server)のセッション発行と保存コールバック。

様式の一時コピーを匿名セッションでブラウザに開かせ、保存された xlsx を
経路2と同じパーサ(parse)→ 登録(regist)へ流す(source='web')。
JWT は必須(secret 未設定は開発時のみ)。読み取れない保存物は xlsx を
添えて IMAP の未処理フォルダへ投函し、メール経路と同じ列に合流させる
(IMAP 不達時は received_dir/web-pending/ へ退避——黙って捨てない)。
"""

import re
import secrets
import urllib.request
import uuid
from email.message import EmailMessage
from pathlib import Path

import jwt as pyjwt
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.core.config import Settings
from app.core.errors import ApiError
from app.models import Course
from app.routers.deps import CfgDep, DbDep, MailerDep
from app.services import forms, mail, mailin, parse, regist

router = APIRouter(tags=["docs"])

_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")  # token_urlsafe 形式のみ許可
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sess_dir(cfg: Settings) -> Path:
    return Path(cfg.received_dir) / "websess"


def _fetch(url: str) -> bytes:
    """Document Server から保存済み xlsx を取得(テストで差し替える)。"""
    with urllib.request.urlopen(url, timeout=30) as res:
        return res.read()


@router.get("/session/{course_id}")
def make_session(course_id: uuid.UUID, db: DbDep, cfg: CfgDep):
    """様式の一時コピーで編集セッションを発行する(匿名・JWT 署名つき)。"""
    course = db.get(Course, course_id)
    if course is None or course.status != "open":
        raise ApiError(404, "この講座は申込を受け付けていません", "course-not-open")

    key = secrets.token_urlsafe(24)
    d = _sess_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    forms.build(course, cfg.submit_addr).save(d / f"{key}.xlsx")

    config = {
        "documentType": "cell",
        "document": {
            "fileType": "xlsx",
            "key": key,
            "title": f"申込書_{course.title}.xlsx",
            "url": f"{cfg.api_base_url}/docs/file/{key}",
        },
        "editorConfig": {
            "lang": "ja",
            "mode": "edit",
            "callbackUrl": f"{cfg.api_base_url}/docs/callback/{key}",
            "user": {"id": f"anon-{key[:8]}", "name": "申込者"},
            "customization": {"forcesave": True, "compactHeader": True},
        },
    }
    if cfg.onlyoffice_jwt_secret:
        config["token"] = pyjwt.encode(
            config, cfg.onlyoffice_jwt_secret, algorithm="HS256"
        )
    return {"docserver": cfg.onlyoffice_url, "config": config}


@router.get("/file/{key}")
def get_file(key: str, cfg: CfgDep):
    """一時コピーの本体(Document Server が取りに来る)。"""
    if not _KEY_RE.match(key):
        raise ApiError(404, "セッションがありません", "session-not-found")
    path = _sess_dir(cfg) / f"{key}.xlsx"
    if not path.exists():
        raise ApiError(404, "セッションがありません", "session-not-found")
    return FileResponse(path, media_type=XLSX_MIME, filename="申込書.xlsx")


def _verify_jwt(data: dict, request: Request, secret: str) -> bool:
    token = data.get("token")
    if not token:
        header = request.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ").strip()
    if not token:
        return False
    try:
        pyjwt.decode(token, secret, algorithms=["HS256"])
        return True
    except pyjwt.InvalidTokenError:
        return False


def _to_pending(cfg: Settings, key: str, xlsx: bytes, issues: list[str]) -> None:
    """読み取れない保存物を未処理キュー(IMAP)へ。不達ならファイル退避。"""
    msg = EmailMessage()
    msg["From"] = cfg.submit_addr
    msg["To"] = cfg.submit_addr
    msg["Subject"] = "【ブラウザ記入・要確認】読み取れない申込"
    msg.set_content(
        "ブラウザ記入の保存内容が読み取れませんでした。\n\n"
        + "\n".join(f"・{s}" for s in issues)
    )
    msg.add_attachment(
        xlsx,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{key}.xlsx",
    )
    try:
        box = mailin.ImapBox(cfg)
        try:
            box.append(cfg.imap_pending, msg.as_bytes())
        finally:
            box.close()
    except Exception:  # noqa: BLE001 - IMAP 不達でも捨てない
        d = Path(cfg.received_dir) / "web-pending"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{key}.xlsx").write_bytes(xlsx)
        (d / f"{key}.txt").write_text("\n".join(issues), encoding="utf-8")


@router.post("/callback/{key}")
async def callback(
    key: str,
    request: Request,
    db: DbDep,
    cfg: CfgDep,
    mailer: MailerDep,
):
    """Document Server の保存コールバック。届いた xlsx を経路2と同じ列へ。"""
    if not _KEY_RE.match(key):
        raise ApiError(404, "セッションがありません", "session-not-found")
    data = await request.json()
    if cfg.onlyoffice_jwt_secret and not _verify_jwt(
        data, request, cfg.onlyoffice_jwt_secret
    ):
        raise ApiError(403, "署名が確認できません", "invalid-token")

    # 2=保存(閉じた) / 6=強制保存。それ以外(開いた・編集中)は受領のみ
    if data.get("status") not in (2, 6):
        return {"error": 0}

    xlsx = _fetch(data["url"])
    try:
        form = parse.parse(xlsx)
        application = regist.regist(db, form, source="web")
        d = Path(cfg.received_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{application.application_no}.xlsx"
        path.write_bytes(xlsx)
        application.received_file = str(path)
        course = db.get(Course, form.course_id)
        subject, body = mail.receipt(application, course, form.entrants)
        db.commit()
    except (parse.Invalid, regist.Rejected) as e:
        db.rollback()
        _to_pending(cfg, key, xlsx, e.issues)
        return {"error": 1}

    mailer.send(form.contact_email, subject, body)
    (_sess_dir(cfg) / f"{key}.xlsx").unlink(missing_ok=True)
    return {"error": 0}

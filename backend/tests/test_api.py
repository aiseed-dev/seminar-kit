"""公開 API の検査(組み込み PostgreSQL+TestClient)。

講座一覧・詳細・QR・経路1(セッション発行→保存コールバック)まで通す。
個人情報・meeting_url が公開 API に漏れないことを機械的に確かめる。
"""

import io
import uuid
from datetime import datetime, timedelta

import jwt as pyjwt
import pytest
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.main import app
from app.models import Application, Base, Category, Course
from app.routers import docs
from app.services import forms, mail
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.db

NOW = datetime(2026, 8, 1, 10, 0, tzinfo=forms.JST)
SECRET = "test-jwt-secret-0123456789abcdef"  # HS256 推奨長(32バイト)以上


@pytest.fixture(scope="module")
def engine(test_db_url):
    eng = create_engine(test_db_url)
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS seminar")
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(scope="module")
def seed(engine):
    with Session(engine) as s:
        cat = Category(slug="dx", name="デジタル化・DX")
        s.add(cat)
        s.flush()
        open_course = Course(
            id=uuid.uuid4(),
            title="DX入門セミナー",
            category_id=cat.id,
            status="open",
            starts_at=NOW + timedelta(days=30),
            apply_deadline=NOW + timedelta(days=20),
            allow_venue=True,
            allow_online=True,
            capacity_venue=30,
            meeting_url="https://jitsi.example.jp/secret-room",
        )
        draft = Course(
            id=uuid.uuid4(),
            title="下書き講座",
            category_id=cat.id,
            status="draft",
            starts_at=NOW,
            apply_deadline=NOW,
        )
        s.add_all([open_course, draft])
        s.commit()
        return {"open": open_course.id, "draft": draft.id}


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, *, reply_to=None):
        self.sent.append((to, subject, body))


@pytest.fixture
def client(engine, tmp_path):
    cfg = Settings(
        onlyoffice_jwt_secret=SECRET,
        form_secret="api-form-secret",  # 発行キー検証を有効にして通す
        api_base_url="http://testserver/api/v1",
        onlyoffice_url="http://docserver.example",
        received_dir=str(tmp_path / "received"),
        imap_host="127.0.0.1",
        imap_port=1,  # 届かない(未処理はファイル退避に落ちる)
    )
    mailer = FakeMailer()

    def override_db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: cfg
    app.dependency_overrides[mail.get_mailer] = lambda: mailer
    c = TestClient(app)
    c.mailer = mailer
    c.cfg = cfg
    yield c
    app.dependency_overrides.clear()


def test_list_courses_open_only(client, seed):
    res = client.get("/api/v1/courses")
    assert res.status_code == 200
    titles = [c["title"] for c in res.json()]
    assert "DX入門セミナー" in titles
    assert "下書き講座" not in titles
    # 個人情報も配信URLも含まれない
    assert "secret-room" not in res.text
    assert "meeting_url" not in res.text


def test_category_filter(client, seed):
    assert len(client.get("/api/v1/courses?category=dx").json()) == 1
    assert client.get("/api/v1/courses?category=nashi").json() == []


def test_course_detail(client, seed):
    res = client.get(f"/api/v1/courses/{seed['open']}")
    assert res.status_code == 200
    body = res.json()
    assert body["has_venue_seats"] is True
    assert body["locations"] == ["会場", "オンライン"]
    assert "secret-room" not in res.text


def test_draft_is_404_with_code(client, seed):
    res = client.get(f"/api/v1/courses/{seed['draft']}")
    assert res.status_code == 404
    assert res.json() == {"detail": "講座が見つかりません", "code": "course-not-found"}


def test_qr_png(client, seed):
    res = client.get(f"/api/v1/qr/c/{seed['open']}.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content[:4] == b"\x89PNG"


# ---- 経路1(セッション発行 → コールバック) ----


def make_session(client, seed):
    res = client.get(f"/api/v1/docs/session/{seed['open']}")
    assert res.status_code == 200
    return res.json()


def test_session_config_signed(client, seed):
    sess = make_session(client, seed)
    assert sess["docserver"] == "http://docserver.example"
    config = sess["config"]
    decoded = pyjwt.decode(config["token"], SECRET, algorithms=["HS256"])
    assert decoded["document"]["key"] == config["document"]["key"]
    # 一時コピーが取得できる(空の様式)
    key = config["document"]["key"]
    res = client.get(f"/api/v1/docs/file/{key}")
    assert res.status_code == 200
    assert res.content[:2] == b"PK"  # xlsx(zip)


def test_session_draft_course_rejected(client, seed):
    res = client.get(f"/api/v1/docs/session/{seed['draft']}")
    assert res.status_code == 404


def fill_form(raw: bytes, course_id) -> bytes:
    wb = load_workbook(io.BytesIO(raw))

    def put(name, value):
        ((title, coord),) = wb.defined_names[name].destinations
        wb[title][coord] = value

    put("company_kana", "カブシキガイシャウェブ")
    put("company_name", "株式会社ウェブ")
    put("postal_code", "770-0000")
    put("address", "徳島市")
    put("tel", "088-000-0000")
    put("contact_kana", "ウェブ タロウ")
    put("contact_name", "ウェブ 太郎")
    put("contact_email", "web@example.jp")
    put("att1_name", "ウェブ 花子")
    put("att1_kana", "ウェブ ハナコ")
    put("att1_role", "企画部")
    put("att1_email", "hanako@example.jp")
    put("att1_loc", "オンライン")
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def signed_callback(key: str, **extra) -> dict:
    data = {"key": key, "status": 2, "url": "http://docserver.example/dl", **extra}
    data["token"] = pyjwt.encode(data, SECRET, algorithm="HS256")
    return data


def test_callback_registers(client, seed, engine, monkeypatch):
    sess = make_session(client, seed)
    key = sess["config"]["document"]["key"]
    empty = client.get(f"/api/v1/docs/file/{key}").content
    monkeypatch.setattr(docs, "_fetch", lambda url: fill_form(empty, seed["open"]))

    res = client.post(f"/api/v1/docs/callback/{key}", json=signed_callback(key))
    assert res.status_code == 200
    assert res.json() == {"error": 0}

    with Session(engine) as s:
        a = s.scalar(select(Application).where(Application.source == "web"))
        assert a is not None
        assert a.company_name == "株式会社ウェブ"
        assert a.received_file.endswith(f"{a.application_no}.xlsx")
    ((to, subject, _),) = client.mailer.sent
    assert to == "web@example.jp" and "【受付】" in subject
    # 一時コピーは破棄される
    assert client.get(f"/api/v1/docs/file/{key}").status_code == 404


def test_callback_invalid_goes_pending(client, seed, monkeypatch, tmp_path):
    sess = make_session(client, seed)
    key = sess["config"]["document"]["key"]
    monkeypatch.setattr(docs, "_fetch", lambda url: b"broken-bytes")

    res = client.post(f"/api/v1/docs/callback/{key}", json=signed_callback(key))
    assert res.status_code == 200
    assert res.json() == {"error": 1}
    # IMAP 不達 → ファイル退避(黙って捨てない)
    from pathlib import Path

    fallback = Path(client.cfg.received_dir) / "web-pending" / f"{key}.xlsx"
    assert fallback.exists()


def test_callback_requires_jwt(client, seed):
    sess = make_session(client, seed)
    key = sess["config"]["document"]["key"]
    res = client.post(
        f"/api/v1/docs/callback/{key}",
        json={"key": key, "status": 2, "url": "http://x"},
    )
    assert res.status_code == 403


def test_callback_ignores_editing_status(client, seed):
    sess = make_session(client, seed)
    key = sess["config"]["document"]["key"]
    res = client.post(
        f"/api/v1/docs/callback/{key}", json=signed_callback(key, status=1)
    )
    assert res.json() == {"error": 0}

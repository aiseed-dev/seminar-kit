"""静的サイト生成の検査(DB 不要)。"""

import uuid
from datetime import datetime, timedelta

from app.models import Category, Course
from app.services import sitegen
from app.services.forms import JST

NOW = datetime(2026, 8, 1, 10, 0, tzinfo=JST)

CATS = [
    Category(id=1, slug="jinzai", name="人材育成", sort_order=1),
    Category(id=2, slug="dx", name="デジタル化・DX", sort_order=2),
]


def make_course(**over) -> Course:
    base = dict(
        id=uuid.uuid4(),
        title="講座",
        category_id=1,
        status="open",
        starts_at=NOW + timedelta(days=30),
        apply_deadline=NOW + timedelta(days=20),
        allow_venue=True,
        allow_online=True,
        allow_satellite=False,
        fee_note="無料",
        meeting_url="https://jitsi.example.jp/secret-room",  # 出力に漏れてはならない
    )
    base.update(over)
    return Course(**base)


OPEN = make_course(title="DX入門セミナー", category_id=2, summary="はじめの一歩")
CLOSED = make_course(title="締切済み講座", status="closed")
FINISHED = make_course(title="開催済み講座", status="finished")
DRAFT = make_course(title="下書き講座", status="draft")
ALL = [OPEN, CLOSED, FINISHED, DRAFT]


CONTACT = "お申し込み・お問い合わせ: 事務局(電話 088-000-0000)"
SUBMIT = "moshikomi@example.jp"


def build(tmp_path):
    sitegen.build_site(
        ALL,
        CATS,
        tmp_path,
        base_url="https://kensyu.example.jp",
        contact_note=CONTACT,
        submit_addr=SUBMIT,
        form_secret="test-secret",
    )
    return tmp_path


def test_pages_exist(tmp_path):
    out = build(tmp_path)
    assert (out / "index.html").exists()
    assert (out / "archive.html").exists()
    assert (out / "static" / "style.css").exists()
    for c in (OPEN, CLOSED, FINISHED):
        assert (out / "courses" / str(c.id) / "index.html").exists()
        assert (out / "courses" / str(c.id) / "qr.png").stat().st_size > 0


def test_index_content(tmp_path):
    out = build(tmp_path)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "DX入門セミナー" in index
    assert "締切済み講座" in index
    assert "デジタル化・DX" in index  # 分類見出し
    assert "開催済み講座" not in index  # 開催済みはアーカイブ側
    archive = (out / "archive.html").read_text(encoding="utf-8")
    assert "開催済み講座" in archive


def test_draft_not_published(tmp_path):
    out = build(tmp_path)
    assert not (out / "courses" / str(DRAFT.id)).exists()
    assert "下書き講座" not in (out / "index.html").read_text(encoding="utf-8")


def test_form_published_for_open_course(tmp_path):
    """募集中の講座には様式 xlsx を置く(2026-07-09 決定8)。

    様式は発行キー入りの正規品で、講座IDが機械可読に入っている。
    """
    from openpyxl import load_workbook

    out = build(tmp_path)
    path = out / "courses" / str(OPEN.id) / "form.xlsx"
    assert path.stat().st_size > 0
    wb = load_workbook(path)
    ((title, coord),) = wb.defined_names["course_id"].destinations
    assert str(wb[title][coord].value) == str(OPEN.id)
    # 募集中でない講座には置かない
    assert not (out / "courses" / str(CLOSED.id) / "form.xlsx").exists()
    assert not (out / "courses" / str(FINISHED.id) / "form.xlsx").exists()


def test_form_omitted_without_addr(tmp_path):
    """submit_addr 未設定なら様式は出力しない(宛先のない様式を配らない)。"""
    sitegen.build_site(
        ALL, CATS, tmp_path, base_url="https://x.example.jp", contact_note=CONTACT
    )
    assert list(tmp_path.rglob("*.xlsx")) == []


def test_nothing_secret_leaks(tmp_path):
    """meeting_url も申込アドレスも HTML には出ない(宛先は様式の中にだけ)。"""
    out = build(tmp_path)
    for path in out.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "jitsi.example.jp" not in text, path
        assert "secret-room" not in text, path
        assert "moshikomi@" not in text, path  # 宛先はページに書かない


def test_course_page_content(tmp_path):
    out = build(tmp_path)
    page = (out / "courses" / str(OPEN.id) / "index.html").read_text(encoding="utf-8")
    assert "募集中" in page
    assert 'href="form.xlsx"' in page  # 様式のダウンロード導線(決定8)
    assert "ブラウザで記入して送信" in page
    assert CONTACT in page  # 電話・紙の案内(公開用連絡先)
    closed_page = (out / "courses" / str(CLOSED.id) / "index.html").read_text(
        encoding="utf-8"
    )
    assert "ブラウザで記入して送信" not in closed_page  # 締切後は申込導線なし
    assert "form.xlsx" not in closed_page

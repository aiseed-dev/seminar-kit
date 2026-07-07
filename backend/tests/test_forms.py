"""様式の生成(forms)と読み取り(parse)のラウンドトリップ検査。"""

import io
import uuid
from datetime import datetime

import pytest
from app.models import Course
from app.services import forms, parse
from openpyxl import Workbook, load_workbook

JST = forms.JST
SUBMIT = "moshikomi@example.jp"


def make_course(**over) -> Course:
    base = dict(
        id=uuid.uuid4(),
        title="DX入門セミナー",
        starts_at=datetime(2026, 9, 1, 13, 30, tzinfo=JST),
        apply_deadline=datetime(2026, 8, 25, 17, 0, tzinfo=JST),
        allow_venue=True,
        allow_online=True,
        allow_satellite=False,
        satellite_note=None,
    )
    base.update(over)
    return Course(**base)


def build_wb(course: Course):
    buf = io.BytesIO()
    forms.build(course, SUBMIT).save(buf)
    buf.seek(0)
    return load_workbook(buf)


def set_named(wb, name: str, value) -> None:
    ((title, coord),) = wb.defined_names[name].destinations
    wb[title][coord] = value


def dump(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


COMPANY = {
    "company_kana": "カブシキガイシャテスト",
    "company_name": "株式会社テスト",
    "postal_code": "770-8570",
    "address": "徳島県徳島市万代町1-1",
    "tel": "088-621-2323",
    "contact_kana": "トクシマ タロウ",
    "contact_name": "徳島 太郎",
    "contact_email": "taro@test.example.jp",
}


def fill_company(wb) -> None:
    for name, value in COMPANY.items():
        set_named(wb, name, value)


def fill_att(wb, i: int, loc: str = "会場") -> None:
    set_named(wb, f"att{i}_name", f"受講 {i}郎")
    set_named(wb, f"att{i}_kana", f"ジュコウ {i}ロウ")
    set_named(wb, f"att{i}_role", "総務部")
    set_named(wb, f"att{i}_email", f"user{i}@test.example.jp")
    set_named(wb, f"att{i}_loc", loc)


def test_roundtrip():
    course = make_course()
    wb = build_wb(course)
    fill_company(wb)
    fill_att(wb, 1, "会場")
    got = parse.parse(dump(wb))

    assert got.course_id == course.id
    assert got.form_ver == forms.FORM_VER
    assert got.company_name == COMPANY["company_name"]
    assert got.contact_email == COMPANY["contact_email"]
    assert got.fax is None  # 任意欄は未記入で通る
    (entrant,) = got.entrants
    assert entrant.name == "受講 1郎"
    assert entrant.loc == "venue"


def test_roundtrip_three_entrants():
    wb = build_wb(make_course())
    fill_company(wb)
    fill_att(wb, 1, "会場")
    fill_att(wb, 2, "オンライン")
    fill_att(wb, 3, "会場")
    got = parse.parse(dump(wb))
    assert [e.loc for e in got.entrants] == ["venue", "online", "venue"]


def test_satellite_label_parses():
    course = make_course(allow_satellite=True, satellite_note="toku-Noix")
    labels = forms.loc_labels(course)
    assert labels == ["会場", "オンライン", "サテライト(toku-Noix)"]
    wb = build_wb(course)
    fill_company(wb)
    fill_att(wb, 1, "サテライト(toku-Noix)")
    got = parse.parse(dump(wb))
    assert got.entrants[0].loc == "satellite"


def test_missing_company_field():
    wb = build_wb(make_course())
    fill_company(wb)
    set_named(wb, "company_name", None)
    fill_att(wb, 1)
    with pytest.raises(parse.Invalid) as e:
        parse.parse(dump(wb))
    assert any("企業・団体名" in s for s in e.value.issues)


def test_no_entrants():
    wb = build_wb(make_course())
    fill_company(wb)
    with pytest.raises(parse.Invalid) as e:
        parse.parse(dump(wb))
    assert any("受講者が1名も" in s for s in e.value.issues)


def test_partial_entrant_row():
    wb = build_wb(make_course())
    fill_company(wb)
    fill_att(wb, 1)
    set_named(wb, "att2_name", "名前だけ")  # 2人目は氏名のみ記入
    with pytest.raises(parse.Invalid) as e:
        parse.parse(dump(wb))
    assert any("受講者2人目" in s for s in e.value.issues)


def test_bad_location():
    wb = build_wb(make_course())
    fill_company(wb)
    fill_att(wb, 1, "自宅")
    with pytest.raises(parse.Invalid) as e:
        parse.parse(dump(wb))
    assert any("参加場所" in s for s in e.value.issues)


def test_wrong_version():
    wb = build_wb(make_course())
    fill_company(wb)
    fill_att(wb, 1)
    set_named(wb, "form_ver", 99)
    with pytest.raises(parse.Invalid) as e:
        parse.parse(dump(wb))
    assert any("版" in s for s in e.value.issues)


def test_not_a_form():
    blank = Workbook()
    with pytest.raises(parse.Invalid) as e:
        parse.parse(dump(blank))
    assert any("様式のファイルではない" in s for s in e.value.issues)


def test_form_is_protected_and_machine_readable():
    wb = build_wb(make_course())
    ws = wb[forms.SHEET]
    assert ws.protection.sheet  # シート保護
    assert ws.column_dimensions["H"].hidden  # メタ列は非表示
    # 入力セルは保護解除、メタセルは保護のまま
    assert ws[forms.NAMES["company_name"]].protection.locked is False
    assert ws[forms.NAMES["course_id"]].protection.locked is True
    # 参加場所のドロップダウン(入力規則)がある
    assert len(ws.data_validations.dataValidation) == 1
    # 記入例シートが付いている
    assert "記入例" in wb.sheetnames


def test_all_named_cells_registered():
    wb = build_wb(make_course())
    for name in forms.NAMES:
        assert name in wb.defined_names

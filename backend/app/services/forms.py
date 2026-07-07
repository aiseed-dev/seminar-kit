"""申込様式 xlsx の生成(神Excel を機械可読に設計する)。

様式 xlsx が唯一のフォーム定義。名前付きセルの一覧(NAMES)はここが正で、
読み取り(parse.py)も同じ定義名を参照する。セル座標はこのモジュールに閉じ、
他の場所でハードコードしない。
Excel の定義名にはハイフンが使えないため、定義名のみアンダースコアを使う。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import quote_sheetname
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from app.models.course import Course

FORM_VER = 1
SHEET = "申込書"
JST = ZoneInfo("Asia/Tokyo")

# 参加場所の表示ラベル(申込者が見る値)⇔ DB の location 値
LOC_VENUE = "会場"
LOC_ONLINE = "オンライン"
LOC_SATELLITE = "サテライト"
LOC_JA = {"venue": LOC_VENUE, "online": LOC_ONLINE, "satellite": LOC_SATELLITE}

# 企業・担当者欄: 定義名 → (行, ラベル)。値はいずれも C 列
_COMPANY_ROWS: dict[str, tuple[int, str]] = {
    "company_kana": (5, "フリガナ"),
    "company_name": (6, "企業・団体名"),
    "postal_code": (7, "郵便番号"),
    "address": (8, "所在地"),
    "tel": (9, "電話番号"),
    "fax": (10, "FAX(任意)"),
    "contact_kana": (11, "フリガナ"),
    "contact_name": (12, "ご担当者名"),
    "contact_email": (13, "メールアドレス"),
}

# 受講者欄(最大3名): ヘッダ行の下に1名1行
ATT_FIELDS: dict[str, tuple[str, str]] = {
    "name": ("B", "氏名"),
    "kana": ("C", "フリガナ"),
    "role": ("D", "所属・役職"),
    "email": ("E", "メールアドレス"),
    "loc": ("F", "参加場所"),
}
_ATT_HEADER_ROW = 15
_ATT_ROWS = (16, 17, 18)
_NOTE_ROW = 20

# 定義名 → セル座標(様式の機械可読部の全リスト)
NAMES: dict[str, str] = {
    "course_id": "H1",
    "form_ver": "H2",
    **{name: f"C{row}" for name, (row, _) in _COMPANY_ROWS.items()},
    **{
        f"att{i}_{field}": f"{col}{_ATT_ROWS[i - 1]}"
        for i in (1, 2, 3)
        for field, (col, _) in ATT_FIELDS.items()
    },
}

REQUIRED = [n for n in _COMPANY_ROWS if n != "fax"]  # 企業欄の必須(FAXのみ任意)

# 不備メッセージ用の日本語ラベル
LABELS: dict[str, str] = {
    **{name: label for name, (_, label) in _COMPANY_ROWS.items()},
    **{f"att{i}_{f}": label for i in (1, 2, 3) for f, (_, label) in ATT_FIELDS.items()},
}


def loc_labels(course: Course) -> list[str]:
    """講座が提供する参加場所のドロップダウン選択肢。"""
    labels = []
    if course.allow_venue:
        labels.append(LOC_VENUE)
    if course.allow_online:
        labels.append(LOC_ONLINE)
    if course.allow_satellite:
        note = (course.satellite_note or "").replace(",", "、").strip()
        labels.append(f"{LOC_SATELLITE}({note})" if note else LOC_SATELLITE)
    return labels


def label_to_loc(label: str) -> str | None:
    """表示ラベル → DB の location 値。判別できなければ None。"""
    s = label.strip()
    if s.startswith(LOC_SATELLITE):
        return "satellite"
    if s.startswith(LOC_ONLINE):
        return "online"
    if s.startswith(LOC_VENUE):
        return "venue"
    return None


def jst(dt: datetime) -> str:
    """JST の日本語表記(様式・静的サイトで共用)。"""
    d = dt.astimezone(JST)
    return f"{d.year}年{d.month}月{d.day}日 {d:%H:%M}"


_FILL_INPUT = PatternFill("solid", fgColor="FFFDE7")  # 記入欄(薄い黄色)
_THIN = Side(style="thin")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _draw(ws: Worksheet, course: Course, submit_addr: str) -> None:
    """レイアウト(ラベル・見出し・案内文)を描く。申込書・記入例で共通。"""
    ws["A1"] = "受講申込書"
    ws["A1"].font = Font(size=16, bold=True)
    ws["A2"] = "講座名"
    ws["B2"] = course.title
    ws["B2"].font = Font(bold=True)
    ws["A3"] = "開催日"
    ws["B3"] = jst(course.starts_at)
    ws["A4"] = "申込期限"
    ws["B4"] = jst(course.apply_deadline)

    for row, label in _COMPANY_ROWS.values():
        ws[f"A{row}"] = label
        cell = ws[f"C{row}"]
        cell.fill = _FILL_INPUT
        cell.border = _BORDER

    ws[f"A{_ATT_HEADER_ROW}"] = "受講者(最大3名)"
    ws[f"A{_ATT_HEADER_ROW}"].font = Font(bold=True)
    for col, label in ATT_FIELDS.values():
        head = ws[f"{col}{_ATT_HEADER_ROW}"]
        head.value = label
        head.border = _BORDER
        head.alignment = Alignment(horizontal="center")
        for row in _ATT_ROWS:
            cell = ws[f"{col}{row}"]
            cell.fill = _FILL_INPUT
            cell.border = _BORDER

    ws[f"A{_NOTE_ROW}"] = (
        f"記入後、このファイルをメールに添付して {submit_addr} へお送りください。"
        "印刷して FAX でもお申し込みいただけます。"
    )

    ws.column_dimensions["A"].width = 16
    for col in "BCDE":
        ws.column_dimensions[col].width = 22
    ws.column_dimensions["F"].width = 18
    ws.print_area = f"A1:F{_NOTE_ROW}"
    ws.page_setup.fitToWidth = 1


def build(course: Course, submit_addr: str) -> Workbook:
    """講座ごとの申込様式を組み立てる(1枚目=申込書、2枚目=記入例)。"""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    _draw(ws, course, submit_addr)

    # 機械可読メタ(印刷範囲外の列に置き、非表示にする)
    ws[NAMES["course_id"]] = str(course.id)
    ws[NAMES["form_ver"]] = FORM_VER
    ws.column_dimensions["H"].hidden = True

    for name, coord in NAMES.items():
        ref = f"{quote_sheetname(SHEET)}!${coord[0]}${coord[1:]}"
        wb.defined_names[name] = DefinedName(name, attr_text=ref)

    # 参加場所はドロップダウン(講座が提供する場所のみ)
    labels = loc_labels(course)
    dv = DataValidation(
        type="list",
        formula1='"' + ",".join(labels) + '"',
        allow_blank=True,
        showErrorMessage=True,
        error="リストから選んでください",
    )
    ws.add_data_validation(dv)
    for i in (1, 2, 3):
        dv.add(ws[NAMES[f"att{i}_loc"]])

    # 入力セル以外はシート保護
    for name, coord in NAMES.items():
        if name not in ("course_id", "form_ver"):
            ws[coord].protection = Protection(locked=False)
    ws.protection.sheet = True

    _example(wb, course, submit_addr, labels)
    return wb


_SAMPLE_COMPANY = {
    "company_kana": "カブシキガイシャ マルマルセイサクショ",
    "company_name": "株式会社 ○○製作所",
    "postal_code": "770-0000",
    "address": "徳島県徳島市○○町1-2-3",
    "tel": "088-000-0000",
    "fax": "088-000-0001",
    "contact_kana": "ヤマダ ハナコ",
    "contact_name": "山田 花子",
    "contact_email": "hanako@example.co.jp",
}


def _example(wb: Workbook, course: Course, submit_addr: str, labels: list[str]) -> None:
    """記入例シート(2枚目)。迷わせないための見本で、機械読み取りはしない。"""
    ws = wb.create_sheet("記入例")
    _draw(ws, course, submit_addr)
    for name, value in _SAMPLE_COMPANY.items():
        row, _ = _COMPANY_ROWS[name]
        ws[f"C{row}"] = value
    sample_att = {
        "name": "山田 太郎",
        "kana": "ヤマダ タロウ",
        "role": "製造部 課長",
        "email": "taro@example.co.jp",
        "loc": labels[0] if labels else LOC_VENUE,
    }
    for field, (col, _) in ATT_FIELDS.items():
        ws[f"{col}{_ATT_ROWS[0]}"] = sample_att[field]
    ws.protection.sheet = True

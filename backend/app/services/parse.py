"""申込様式 xlsx の読み取り(3経路共通のパーサ)。

位置は名前付きセル(forms.NAMES と同じ定義名)で参照し、座標を
ハードコードしない。ファイルの中身だけで判る不備はここで検出して
Invalid(issues つき)を送出する。講座の状態に依存する検証
(期限・定員・参加場所の提供有無)は登録側(regist)が行う。
"""

import io
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from openpyxl import load_workbook
from openpyxl.workbook import Workbook

from app.services import forms


@dataclass(frozen=True)
class Entrant:
    """様式から読み取った受講者1名分。loc は DB の location 値。"""

    name: str
    kana: str
    role: str
    email: str
    loc: str


@dataclass(frozen=True)
class FormData:
    """様式から読み取った申込1件分(検証済み)。"""

    course_id: uuid.UUID
    form_ver: int
    company_name: str
    company_kana: str
    contact_name: str
    contact_kana: str
    contact_email: str
    postal_code: str
    address: str
    tel: str
    fax: str | None
    entrants: tuple[Entrant, ...]


class Invalid(Exception):
    """様式の不備。issues は申込者向けの修正依頼文にそのまま使える日本語。"""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__(" / ".join(issues))


def _value(wb: Workbook, name: str) -> str | None:
    """定義名のセル値を文字列で返す(空・空白のみは None)。"""
    dn = wb.defined_names.get(name)
    if dn is None:
        return None
    try:
        ((title, coord),) = dn.destinations
    except ValueError:
        return None
    v = wb[title][coord].value
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse(src: bytes | BinaryIO | Path) -> FormData:
    """様式 xlsx を読み取る。様式でない・不備のときは Invalid を送出。"""
    if isinstance(src, bytes):
        src = io.BytesIO(src)
    try:
        wb = load_workbook(src, data_only=True)
    except Exception:  # 壊れた zip・xlsx 以外など、開けないものはすべて「様式でない」
        raise Invalid(
            ["申込様式のファイルではないようです。講座ページの様式をご利用ください。"]
        ) from None

    raw_course = _value(wb, "course_id")
    raw_ver = _value(wb, "form_ver")
    if raw_course is None or raw_ver is None:
        raise Invalid(
            ["申込様式のファイルではないようです。講座ページの様式をご利用ください。"]
        )
    if not raw_ver.isdigit() or int(raw_ver) != forms.FORM_VER:
        raise Invalid(
            [
                f"様式の版が異なります(お手元の版: {raw_ver})。"
                "お手数ですが講座ページから最新の様式をダウンロードしてください。"
            ]
        )
    try:
        course_id = uuid.UUID(raw_course)
    except ValueError:
        raise Invalid(
            ["様式の講座情報が壊れています。講座ページの様式をご利用ください。"]
        ) from None

    issues: list[str] = []
    company: dict[str, str | None] = {}
    for name in forms.REQUIRED:
        company[name] = _value(wb, name)
        if company[name] is None:
            issues.append(f"「{forms.LABELS[name]}」が未記入です")
    company["fax"] = _value(wb, "fax")

    entrants: list[Entrant] = []
    for i in (1, 2, 3):
        fields = {f: _value(wb, f"att{i}_{f}") for f in forms.ATT_FIELDS}
        if not any(fields.values()):
            continue
        missing = [f for f, v in fields.items() if v is None]
        if missing:
            labels = "・".join(forms.LABELS[f"att{i}_{f}"] for f in missing)
            issues.append(f"受講者{i}人目の「{labels}」が未記入です")
            continue
        loc = forms.label_to_loc(fields["loc"])
        if loc is None:
            issues.append(
                f"受講者{i}人目の「参加場所」({fields['loc']})が読み取れません。"
                "ドロップダウンから選んでください"
            )
            continue
        entrants.append(
            Entrant(
                name=fields["name"],
                kana=fields["kana"],
                role=fields["role"],
                email=fields["email"],
                loc=loc,
            )
        )
    if not entrants and not issues:
        issues.append("受講者が1名も記入されていません")

    if issues:
        raise Invalid(issues)

    return FormData(
        course_id=course_id,
        form_ver=int(raw_ver),
        company_name=company["company_name"],
        company_kana=company["company_kana"],
        contact_name=company["contact_name"],
        contact_kana=company["contact_kana"],
        contact_email=company["contact_email"],
        postal_code=company["postal_code"],
        address=company["address"],
        tel=company["tel"],
        fax=company["fax"],
        entrants=tuple(entrants),
    )

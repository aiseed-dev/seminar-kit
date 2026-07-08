"""申込様式の読み取り(全経路共通のパーサ)。

入口は2つ、検証は1つ:
  parse(src)       xlsx(添付・ブラウザ記入)。名前付きセルで読む
  parse_text(body) メール本文の送信用テキスト(`項目: 値`。様式内蔵の
                   マクロが生成する。厳密な YAML ではなく行単位で寛容に読む)
どちらも同じ検証(_assemble)に合流する。ファイル/本文の中身だけで判る
不備はここで検出して Invalid(issues つき)を送出する。講座の状態に依存する
検証(期限・定員・参加場所の提供有無)は登録側(regist)が行う。
"""

import io
import re
import uuid
from collections.abc import Callable
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


def _assemble(value_of: Callable[[str], str | None], secret: str) -> FormData:
    """定義名→値の関数から FormData を組み立てる(xlsx・本文テキスト共通)。"""
    raw_course = value_of("course_id")
    raw_ver = value_of("form_ver")
    if raw_course is None or raw_ver is None:
        raise Invalid(
            ["申込様式のファイルではないようです。講座ページの様式をご利用ください。"]
        )
    if not raw_ver.isdigit() or int(raw_ver) != forms.FORM_VER:
        raise Invalid(
            [
                f"様式の版が異なります(お手元の版: {raw_ver})。"
                "お手数ですが最新の様式をご利用ください。"
            ]
        )
    try:
        course_id = uuid.UUID(raw_course)
    except ValueError:
        raise Invalid(
            ["様式の講座情報が壊れています。最新の様式をご利用ください。"]
        ) from None

    if secret and value_of("form_key") != forms.form_key(course_id, secret):
        raise Invalid(
            [
                "申込様式の発行元が確認できませんでした。"
                "お手数ですが、受領メールまたはチラシ記載の方法でお申し込みください。"
            ]
        )

    issues: list[str] = []
    company: dict[str, str | None] = {}
    for name in forms.REQUIRED:
        company[name] = value_of(name)
        if company[name] is None:
            issues.append(f"「{forms.LABELS[name]}」が未記入です")
    company["fax"] = value_of("fax")

    entrants: list[Entrant] = []
    for i in (1, 2, 3):
        fields = {f: value_of(f"att{i}_{f}") for f in forms.ATT_FIELDS}
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
                f"受講者{i}人目の「参加場所」({fields['loc']})が読み取れません"
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


def parse(src: bytes | BinaryIO | Path, secret: str = "") -> FormData:
    """様式 xlsx を読み取る。様式でない・不備のときは Invalid を送出。

    secret を渡すと発行キー(forms.form_key)を検証する。
    キー不一致=当方が発行した様式ではない(捏造・改変)→ Invalid。
    """
    if isinstance(src, bytes):
        src = io.BytesIO(src)
    try:
        wb = load_workbook(src, data_only=True)
    except Exception:  # 壊れた zip・xlsx 以外など、開けないものはすべて「様式でない」
        raise Invalid(
            ["申込様式のファイルではないようです。講座ページの様式をご利用ください。"]
        ) from None
    return _assemble(lambda name: _value(wb, name), secret)


_LINE_RE = re.compile(r"^\s*([^::]{1,20})[::]\s*(.*?)\s*$")


def parse_text(body: str, secret: str = "") -> FormData | None:
    """メール本文の送信用テキストを読み取る。

    「講座ID:」行が無ければ送信用テキストではない → None(呼び出し側は
    経路3などへ流す)。あれば xlsx と同じ検証を通し、不備は Invalid。
    行単位の `項目: 値` を寛容に読む(前後の空白・引用符・全角コロン可)。
    """
    fields: dict[str, str] = {}
    for line in body.splitlines():
        line = line.lstrip('> "')  # 返信の引用・単一セル貼り付けの引用符に耐える
        m = _LINE_RE.match(line)
        if not m:
            continue
        key, value = m.group(1).strip(), m.group(2).strip()
        if key and value and key not in fields:
            fields[key] = value

    if forms.TEXT_KEYS["course_id"] not in fields:
        return None

    def value_of(name: str) -> str | None:
        return fields.get(forms.TEXT_KEYS[name]) or None

    return _assemble(value_of, secret)

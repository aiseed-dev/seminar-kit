"""申込番号の採番。方式は設定(SEMINAR_NO_STYLE)で切り替える。

規模に合わせて選ぶ(2026-07-08 決定。切替可能にすること自体が
「規模に道具を合わせる」の実例・教材を兼ねる):

  seq     全体の通し連番。年は表示のみ(例 2026-00042)。既定
  fy      年度(4月起点)ごとにリセット(例 2026-00007)
  fy-cat  年度-分類-何回目(例 2026-DX-3)。番号を見れば内容が
          わかる小規模運用向け。ゼロ埋めしない

いずれも申込番号は UNIQUE。採番から INSERT までの間に他の申込が入ると
衝突するので、呼び出し側(regist)は IntegrityError で再採番してリトライする
(小規模ではまず起きないが、対策が数行で済むため入れてある)。
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.application import Application
from app.services.ledger import fiscal_year

WIDTH = 5  # seq / fy 方式の連番桁数(不足時は自然に桁あふれして伸びる)

STYLES = ("seq", "fy", "fy-cat")


def parse(no: str) -> tuple[int, int]:
    """申込番号 → (年, 連番)。分類コード入り(2026-DX-3)にも対応。"""
    parts = no.split("-")
    if len(parts) < 2 or not (parts[0].isdigit() and parts[-1].isdigit()):
        raise ValueError(f"申込番号の形式が不正: {no!r}")
    return int(parts[0]), int(parts[-1])


def _max_seq(session: Session, *where) -> int:
    return (
        session.scalar(
            select(func.coalesce(func.max(Application.app_seq), 0)).where(*where)
        )
        or 0
    )


def next_no(
    session: Session,
    at: datetime,
    code: str | None = None,
    style: str | None = None,
) -> tuple[str, int, int]:
    """次の申込番号を採番する。戻り値は (申込番号, 年, 連番)。

    code は講座の分類 slug(fy-cat のときだけ使う)。
    """
    style = style or get_settings().no_style
    if style not in STYLES:
        raise ValueError(f"不明な採番方式: {style!r}")

    if style == "seq":
        year = at.year
        seq = _max_seq(session) + 1
        return f"{year}-{seq:0{WIDTH}d}", year, seq

    year = fiscal_year(at)
    if style == "fy":
        seq = _max_seq(session, Application.app_year == year) + 1
        return f"{year}-{seq:0{WIDTH}d}", year, seq

    # fy-cat: 年度-分類-何回目(ゼロ埋めなし)
    prefix = f"{year}-{(code or 'X').upper()}-"
    seq = _max_seq(session, Application.application_no.like(f"{prefix}%")) + 1
    return f"{prefix}{seq}", year, seq

from datetime import UTC, datetime

import pytest
from app.services import no
from app.services.forms import JST


class FakeSession:
    """scalar() が最終連番を返すだけの代役。"""

    def __init__(self, last):
        self.last = last

    def scalar(self, stmt):
        return self.last


def test_parse():
    assert no.parse("2026-00042") == (2026, 42)
    assert no.parse("2026-DX-3") == (2026, 3)


@pytest.mark.parametrize("bad", ["", "2026", "2026-", "-42", "2026-abc", "abc-42"])
def test_parse_invalid(bad):
    with pytest.raises(ValueError):
        no.parse(bad)


def test_seq_first():
    # 申込ゼロ件(coalesce が 0)→ 1 から始まる
    got = no.next_no(FakeSession(0), datetime(2026, 7, 7, tzinfo=UTC), style="seq")
    assert got == ("2026-00001", 2026, 1)


def test_seq_continues_across_years():
    # 通し方式: 年が変わっても連番はリセットしない
    got = no.next_no(FakeSession(42), datetime(2027, 1, 4, tzinfo=UTC), style="seq")
    assert got == ("2027-00043", 2027, 43)


def test_fy_style_uses_fiscal_year():
    # 年度方式: 2027年1月は2026年度。年度内の連番+1
    got = no.next_no(FakeSession(6), datetime(2027, 1, 4, tzinfo=JST), style="fy")
    assert got == ("2026-00007", 2026, 7)


def test_fy_cat_style():
    # 年度-分類-何回目(ゼロ埋めなし)。分類 slug は大文字化
    got = no.next_no(
        FakeSession(2), datetime(2026, 5, 1, tzinfo=JST), code="dx", style="fy-cat"
    )
    assert got == ("2026-DX-3", 2026, 3)


def test_fy_cat_without_code():
    got = no.next_no(FakeSession(0), datetime(2026, 5, 1, tzinfo=JST), style="fy-cat")
    assert got == ("2026-X-1", 2026, 1)


def test_unknown_style():
    with pytest.raises(ValueError):
        no.next_no(FakeSession(0), datetime(2026, 5, 1, tzinfo=JST), style="nope")


def test_default_style_is_seq():
    # 設定の既定は seq(通し連番)
    got = no.next_no(FakeSession(0), datetime(2026, 7, 7, tzinfo=UTC))
    assert got == ("2026-00001", 2026, 1)


def test_roundtrip_all_styles():
    at = datetime(2026, 5, 1, tzinfo=JST)
    for style, code in (("seq", None), ("fy", None), ("fy-cat", "dx")):
        no_str, year, seq = no.next_no(FakeSession(41), at, code=code, style=style)
        assert no.parse(no_str) == (year, seq)

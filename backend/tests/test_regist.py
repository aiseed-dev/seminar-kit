"""登録時の講座状態検証(check)の検査。DB を使う結合は @pytest.mark.db 側。"""

import uuid
from datetime import datetime, timedelta

from app.models import Course
from app.services import regist
from app.services.forms import JST
from app.services.parse import Entrant

NOW = datetime(2026, 8, 1, 10, 0, tzinfo=JST)


def make_course(**over) -> Course:
    base = dict(
        id=uuid.uuid4(),
        title="テスト講座",
        status="open",
        starts_at=NOW + timedelta(days=30),
        apply_deadline=NOW + timedelta(days=20),
        allow_venue=True,
        allow_online=True,
        allow_satellite=False,
        capacity_venue=None,
    )
    base.update(over)
    return Course(**base)


def entrant(loc: str) -> Entrant:
    return Entrant(
        name="受講 太郎",
        kana="ジュコウ タロウ",
        role="総務部",
        email="taro@example.jp",
        loc=loc,
    )


def test_ok():
    course = make_course()
    assert regist.check(course, [entrant("venue")], 0, NOW) == []


def test_closed():
    course = make_course(status="closed")
    issues = regist.check(course, [entrant("venue")], 0, NOW)
    assert any("募集を終了" in s for s in issues)


def test_past_deadline():
    course = make_course(apply_deadline=NOW - timedelta(hours=1))
    issues = regist.check(course, [entrant("venue")], 0, NOW)
    assert any("期限" in s for s in issues)


def test_location_not_offered():
    course = make_course(allow_satellite=False)
    issues = regist.check(course, [entrant("satellite")], 0, NOW)
    assert any("サテライト" in s and "ご用意がありません" in s for s in issues)


def test_capacity_exact_fit():
    course = make_course(capacity_venue=10)
    # 残り2席にちょうど2名 → 通る
    assert regist.check(course, [entrant("venue"), entrant("venue")], 8, NOW) == []


def test_capacity_over():
    course = make_course(capacity_venue=10)
    issues = regist.check(course, [entrant("venue"), entrant("venue")], 9, NOW)
    assert any("定員" in s for s in issues)
    assert any("オンライン" in s for s in issues)  # 代替の案内つき


def test_capacity_ignores_online():
    course = make_course(capacity_venue=10)
    # オンライン参加は定員に数えない
    assert regist.check(course, [entrant("online")], 10, NOW) == []


def test_offered():
    course = make_course(allow_venue=True, allow_online=False, allow_satellite=True)
    assert regist.offered(course) == {"venue", "satellite"}

"""事務局アプリの全画面が組み立てられることの検査(Flet API 互換の煙テスト)。

DB・IMAP には届かない前提(guarded がエラー表示に落とすところまで含めて
画面が壊れないことを見る)。実データでの画面確認は DB 結線後。
"""

import flet as ft
import pytest
from app.core.config import Settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from office import views
from office.auth import Stub


class FakePage:
    """build 時に触られる page API だけ持つ代役。"""

    def update(self):
        pass

    def open(self, *_):
        pass

    def close(self, *_):
        pass


class FakeMailer:
    def send(self, *a, **k):
        pass


@pytest.fixture
def ctx():
    cfg = Settings(db_url="postgresql+psycopg://127.0.0.1:1/none")  # 届かないDB
    engine = create_engine(cfg.db_url)
    return views.Ctx(
        page=FakePage(),
        db=sessionmaker(bind=engine),
        cfg=cfg,
        staff=Stub().login("dev", "dev"),
        mailer=FakeMailer(),
    )


@pytest.mark.parametrize(
    "build",
    [
        views.build_dashboard,
        views.build_courses,
        views.build_apps,
        views.build_inbox,
        views.build_entry,
        views.build_companies,
        views.build_bulk,
        views.build_reports,
        views.build_export,
        views.build_staff,
    ],
)
def test_view_builds(ctx, build):
    control = build(ctx)
    assert isinstance(control, ft.Control)


def test_parse_dt_roundtrip():
    dt = views.parse_dt("2026-09-01 13:30")
    assert views.fmt_dt(dt) == "2026-09-01 13:30"
    assert views.parse_dt("") is None
    with pytest.raises(ValueError):
        views.parse_dt("9月1日")

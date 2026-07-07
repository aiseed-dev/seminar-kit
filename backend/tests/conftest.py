"""DB 結合テスト(@pytest.mark.db)用の PostgreSQL。

TEST_DB_URL があればそれを使い、無ければ pgserver(pip 同梱の PostgreSQL)を
テスト実行中だけ起動する。SQLite は使わない——スキーマが gen_random_uuid /
TIMESTAMPTZ / スキーマ名を使っており、本番と同じ PostgreSQL で検証する。
"""

import os

import pytest


@pytest.fixture(scope="session")
def test_db_url(tmp_path_factory):
    url = os.environ.get("TEST_DB_URL")
    if url:
        yield url
        return
    pgserver = pytest.importorskip(
        "pgserver", reason="TEST_DB_URL 未設定かつ pgserver 未導入"
    )
    pg = pgserver.get_server(tmp_path_factory.mktemp("pgdata"))
    try:
        yield pg.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    finally:
        pg.cleanup()

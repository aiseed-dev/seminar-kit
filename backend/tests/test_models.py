"""モデルが db/schema.sql と食い違っていないかの静的な検査(DB 不要)。"""

import pytest
from app.models import Application, Attendee, Base, Course
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

EXPECTED_TABLES = {
    "staff",
    "categories",
    "courses",
    "companies",
    "applications",
    "attendees",
    "mails",
}


def test_all_tables_defined():
    assert {t.name for t in Base.metadata.tables.values()} == EXPECTED_TABLES


def test_schema_is_seminar():
    assert all(t.schema == "seminar" for t in Base.metadata.tables.values())


def test_ddl_compiles_for_postgresql():
    # PostgreSQL 方言で CREATE TABLE が組み立てられること(構文の通し検査)
    for table in Base.metadata.tables.values():
        str(CreateTable(table).compile(dialect=postgresql.dialect()))


def test_application_no_unique():
    col = Application.__table__.c.application_no
    assert col.unique and not col.nullable


def test_attendee_cascade():
    (fk,) = Attendee.__table__.c.application_id.foreign_keys
    assert fk.ondelete == "CASCADE"


def test_course_status_default():
    assert Course.__table__.c.status.server_default.arg.text == "'draft'"


@pytest.mark.db
def test_schema_sql_matches_models(test_db_url):
    """正である db/schema.sql を実行し、models と表・列が一致することを検査。

    (他のテストは models 経由で DDL を作るため、schema.sql 自体の妥当性と
    「schema.sql を先に直す」規約の守られ具合はここで担保する)
    """
    from pathlib import Path

    from sqlalchemy import inspect

    sql = (Path(__file__).resolve().parents[2] / "db" / "schema.sql").read_text(
        encoding="utf-8"
    )
    engine = create_engine(test_db_url)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS seminar CASCADE")
        conn.exec_driver_sql(sql)
    insp = inspect(engine)
    assert set(insp.get_table_names(schema="seminar")) == EXPECTED_TABLES
    for table in Base.metadata.tables.values():
        db_cols = {c["name"]: c for c in insp.get_columns(table.name, schema="seminar")}
        assert set(db_cols) == {c.name for c in table.columns}, table.name
        for col in table.columns:  # NULL 制約も一致
            assert db_cols[col.name]["nullable"] == col.nullable, (
                f"{table.name}.{col.name}"
            )


@pytest.mark.db
def test_create_and_insert_roundtrip(test_db_url):
    """実 PostgreSQL でテーブル作成と INSERT が通ること。"""
    engine = create_engine(test_db_url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS seminar")
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        from app.models import Category

        session.add(Category(slug="jinzai", name="人材育成"))
        session.commit()

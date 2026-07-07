"""DB 接続。engine は初回利用時に作る(接続情報が無くても import は通る)。"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().db_url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine())


def get_db():
    """FastAPI 依存(1リクエスト=1セッション)。"""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()

"""モデルの基底。db/schema.sql が正——変更はまず schema.sql を直し、ここを追随させる。"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "seminar"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)

from sqlalchemy import Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Category(Base):
    """分類(人材育成 / 資金 / 経営相談 / 販路開拓 / 創業 / 改善活動 /
    技術開発 / デジタル化・DX)"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # SERIAL
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Staff(Base):
    """事務局スタッフ(PocketBase の身元に対応。申込者は登録しない)"""

    __tablename__ = "staff"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # PocketBase record id
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_label: Mapped[str | None] = mapped_column(Text)  # 担当部署名
    role: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("role IN ('staff', 'admin')"),
        nullable=False,
        server_default=text("'staff'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

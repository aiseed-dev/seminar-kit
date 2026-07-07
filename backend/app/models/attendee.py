import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Attendee(Base):
    """受講者(1申込につき1〜3名。個人別の出欠は DB で持たない——
    当日名簿は xlsx で出力し、受付は紙でチェックする運用)"""

    __tablename__ = "attendees"
    __table_args__ = (Index("idx_attendees_app", "application_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kana: Mapped[str] = mapped_column(Text, nullable=False)
    title_role: Mapped[str] = mapped_column(Text, nullable=False)  # 所属・役職
    email: Mapped[str] = mapped_column(Text, nullable=False)  # 接続情報の送付先
    location: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("location IN ('venue', 'online', 'satellite')"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )

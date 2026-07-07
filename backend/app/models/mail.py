import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Mail(Base):
    """一斉送信の記録(配信URL・リマインド・開催案内の変更等)"""

    __tablename__ = "mails"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("courses.id"), nullable=False
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # 宛先の絞り込み(confirmed の受講者のみが対象)
    target: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("target IN ('all', 'venue', 'online', 'satellite')"),
        nullable=False,
        server_default=text("'all'"),
    )
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_by: Mapped[str | None] = mapped_column(Text, ForeignKey("staff.id"))
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Course(Base):
    """講座(セミナー・研修)。公開分は静的サイトに生成される"""

    __tablename__ = "courses"
    __table_args__ = (
        Index(
            "idx_courses_open", "starts_at", postgresql_where=text("status = 'open'")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text)  # 一覧用の一言
    description: Mapped[str | None] = mapped_column(Text)  # 概要(講師紹介・内容)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue_note: Mapped[str | None] = mapped_column(Text)  # 会場(名称・住所・案内)
    # 参加場所の提供有無(会場 / ZOOM / サテライト会場)
    allow_venue: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    allow_online: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    allow_satellite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    satellite_note: Mapped[str | None] = mapped_column(Text)  # サテライト会場名
    # 会場定員(NULL=定員なし)。オンラインは定員管理しない
    capacity_venue: Mapped[int | None] = mapped_column(Integer)
    fee_note: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'無料'")
    )
    apply_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    flyer_path: Mapped[str | None] = mapped_column(Text)  # チラシPDF
    online_note: Mapped[str | None] = mapped_column(Text)  # 受講方法・視聴環境の定型文
    # オンライン配信URL(自営 Jitsi。公開せず一斉送信でのみ受講者へ届ける)
    meeting_url: Mapped[str | None] = mapped_column(Text)
    # open=募集中 / closed=締切 / finished=開催済み
    status: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("status IN ('draft', 'open', 'closed', 'finished')"),
        nullable=False,
        server_default=text("'draft'"),
    )
    # 出席者数(開催後に事務局が入力。年度実績台帳に反映)
    attendance_count: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(Text, ForeignKey("staff.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

import uuid
from datetime import datetime

from sqlalchemy import (
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


class Application(Base):
    """申込(企業単位。企業情報は申込時点のスナップショットとして保持し、
    companies と紐付け)"""

    __tablename__ = "applications"
    __table_args__ = (Index("idx_apps_course", "course_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("courses.id"), nullable=False
    )
    # 事前登録との紐付け(初回申込で自動 upsert して以後引き当て)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("companies.id")
    )
    # 申込番号: DB全体の通し番号(年+連番。例 2026-00042)。
    # 挿入時にアプリが採番して渡す(既定値なし。UNIQUE衝突を防ぐ)
    application_no: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    app_year: Mapped[int | None] = mapped_column(Integer)
    app_seq: Mapped[int | None] = mapped_column(Integer)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_kana: Mapped[str] = mapped_column(Text, nullable=False)
    contact_name: Mapped[str] = mapped_column(Text, nullable=False)  # 担当者
    contact_kana: Mapped[str] = mapped_column(Text, nullable=False)
    contact_email: Mapped[str] = mapped_column(Text, nullable=False)
    postal_code: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    tel: Mapped[str] = mapped_column(Text, nullable=False)
    fax: Mapped[str | None] = mapped_column(Text)
    # confirmed=受付済み / cancelled=キャンセル。
    # 本人のメールアドレスから届くため確認トークンは不要。
    # キャンセルはメール依頼→事務局が処理
    status: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("status IN ('confirmed', 'cancelled')"),
        nullable=False,
        server_default=text("'confirmed'"),
    )
    # mail=様式xlsxメールの自動読み取り / quick=事前登録済みの簡易メール /
    # web=ブラウザ記入(OnlyOffice Docs) / staff=FAX・紙を事務局が代行入力
    source: Mapped[str] = mapped_column(
        Text,
        CheckConstraint("source IN ('mail', 'quick', 'web', 'staff')"),
        nullable=False,
        server_default=text("'mail'"),
    )
    # 受信した申込xlsxの保存パス(原本の監査証跡)
    received_file: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    note: Mapped[str | None] = mapped_column(Text)  # 事務局メモ

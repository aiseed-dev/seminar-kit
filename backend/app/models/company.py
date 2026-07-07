import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Company(Base):
    """企業マスタ(事前登録)。初回申込で自動登録され、以後は担当者メール
    アドレスで引き当てる"""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_kana: Mapped[str] = mapped_column(Text, nullable=False)
    contact_name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_kana: Mapped[str] = mapped_column(Text, nullable=False)
    # 引き当てキー(送信者アドレス)
    contact_email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    postal_code: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    tel: Mapped[str] = mapped_column(Text, nullable=False)
    fax: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

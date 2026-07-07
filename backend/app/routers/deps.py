"""ルーター共通の依存(Annotated 形式)。"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.services import mail

DbDep = Annotated[Session, Depends(get_db)]
CfgDep = Annotated[Settings, Depends(get_settings)]
MailerDep = Annotated[mail.Mailer, Depends(mail.get_mailer)]

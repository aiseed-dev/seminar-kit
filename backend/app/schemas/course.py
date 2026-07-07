"""公開 API の出力。個人情報・meeting_url は絶対に含めない(規約)。"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import Course
from app.services import forms


class CourseOut(BaseModel):
    id: uuid.UUID
    title: str
    category: str  # 分類 slug
    summary: str | None = None
    description: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    venue_note: str | None = None
    locations: list[str]  # 提供する参加場所(表示ラベル)
    fee_note: str
    apply_deadline: datetime
    flyer: bool  # チラシPDFの有無
    status: str


class CourseDetail(CourseOut):
    has_venue_seats: bool  # 会場残席の有無(数は出さない)


def to_out(course: Course, slug: str) -> dict:
    """モデル → 出力 dict(許可した項目だけを手で写す)。"""
    return {
        "id": course.id,
        "title": course.title,
        "category": slug,
        "summary": course.summary,
        "description": course.description,
        "starts_at": course.starts_at,
        "ends_at": course.ends_at,
        "venue_note": course.venue_note,
        "locations": forms.loc_labels(course),
        "fee_note": course.fee_note,
        "apply_deadline": course.apply_deadline,
        "flyer": bool(course.flyer_path),
        "status": course.status,
    }

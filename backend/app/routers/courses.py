"""公開: 講座一覧・講座詳細(認証不要。募集中のみ・個人情報なし)。"""

import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import Category, Course
from app.routers.deps import DbDep
from app.schemas.course import CourseDetail, CourseOut, to_out
from app.services import regist

router = APIRouter(tags=["courses"])


def _slugs(db: Session) -> dict[int, str]:
    return {c.id: c.slug for c in db.scalars(select(Category))}


@router.get("/courses", response_model=list[CourseOut])
def list_courses(db: DbDep, category: str | None = None):
    slugs = _slugs(db)
    out = [
        to_out(c, slugs.get(c.category_id, ""))
        for c in db.scalars(
            select(Course).where(Course.status == "open").order_by(Course.starts_at)
        )
    ]
    if category:
        out = [c for c in out if c["category"] == category]
    return out


@router.get("/courses/{course_id}", response_model=CourseDetail)
def course_detail(course_id: uuid.UUID, db: DbDep):
    course = db.get(Course, course_id)
    if course is None or course.status == "draft":
        raise ApiError(404, "講座が見つかりません", "course-not-found")
    has_seats = course.capacity_venue is None or (
        regist.venue_taken(db, course.id) < course.capacity_venue
    )
    return to_out(course, _slugs(db).get(course.category_id, "")) | {
        "has_venue_seats": has_seats
    }

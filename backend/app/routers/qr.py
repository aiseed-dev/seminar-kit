"""公開: 講座ページ QR(チラシ印刷用)。"""

import uuid

from fastapi import APIRouter, Response

from app.core.errors import ApiError
from app.models import Course
from app.routers.deps import CfgDep, DbDep
from app.services import qr

router = APIRouter(tags=["qr"])


@router.get("/qr/c/{course_id}.png")
def course_qr(course_id: uuid.UUID, db: DbDep, cfg: CfgDep):
    course = db.get(Course, course_id)
    if course is None or course.status == "draft":
        raise ApiError(404, "講座が見つかりません", "course-not-found")
    png = qr.png(f"{cfg.site_base_url}/courses/{course_id}/")
    return Response(png, media_type="image/png")

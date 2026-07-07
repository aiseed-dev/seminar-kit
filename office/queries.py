"""事務局アプリの DB 照会(画面に渡す形まで整える)。"""

from datetime import datetime

from app.models import Application, Attendee, Category, Company, Course, Mail
from app.models import Staff as StaffRow
from app.services import ledger, regist, roster
from app.services.forms import JST
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session


def categories(s: Session) -> list[Category]:
    return list(s.scalars(select(Category).order_by(Category.sort_order)))


def courses(s: Session, status: str | None = None) -> list[Course]:
    stmt = select(Course).order_by(Course.starts_at.desc())
    if status:
        stmt = stmt.where(Course.status == status)
    return list(s.scalars(stmt))


def app_count(s: Session, course_id) -> int:
    return (
        s.scalar(
            select(func.count())
            .select_from(Application)
            .where(
                Application.course_id == course_id,
                Application.status == "confirmed",
            )
        )
        or 0
    )


def venue_left(s: Session, course: Course) -> str:
    """会場残席の表示文字列(定員なしは「—」)。"""
    if course.capacity_venue is None:
        return "—"
    left = course.capacity_venue - regist.venue_taken(s, course.id)
    return f"{max(left, 0)}"


def recent_apps(s: Session, n: int = 10) -> list[tuple[Application, str]]:
    """直近の申込(講座名つき)。"""
    stmt = (
        select(Application, Course.title)
        .join(Course, Application.course_id == Course.id)
        .order_by(Application.created_at.desc())
        .limit(n)
    )
    return [(a, t) for a, t in s.execute(stmt)]


def apps_for_course(s: Session, course_id, status: str) -> list[Application]:
    return list(
        s.scalars(
            select(Application)
            .where(
                Application.course_id == course_id,
                Application.status == status,
            )
            .order_by(Application.created_at)
        )
    )


def attendees_of(s: Session, application_id) -> list[Attendee]:
    return list(
        s.scalars(
            select(Attendee)
            .where(Attendee.application_id == application_id)
            .order_by(Attendee.sort_order)
        )
    )


def loc_counts(s: Session, course_id) -> dict[str, int]:
    """受付済みの参加場所別人数。"""
    stmt = (
        select(Attendee.location, func.count())
        .join(Application, Attendee.application_id == Application.id)
        .where(
            Application.course_id == course_id,
            Application.status == "confirmed",
        )
        .group_by(Attendee.location)
    )
    return dict(s.execute(stmt).all())


def recipients(s: Session, course_id, target: str) -> list[str]:
    """一斉送信の宛先(確定受講者。target で参加場所を絞る)。重複除去。"""
    stmt = (
        select(Attendee.email)
        .join(Application, Attendee.application_id == Application.id)
        .where(
            Application.course_id == course_id,
            Application.status == "confirmed",
        )
    )
    if target != "all":
        stmt = stmt.where(Attendee.location == target)
    seen: dict[str, None] = {}
    for (addr,) in s.execute(stmt):
        if addr:
            seen.setdefault(addr.lower())
    return list(seen)


def find_app(s: Session, no: str) -> Application | None:
    return s.scalar(select(Application).where(Application.application_no == no.strip()))


def companies(s: Session, q: str = "") -> list[tuple[Company, int]]:
    """企業マスタ(申込件数つき)。q は名称・カナ・メールの部分一致。"""
    stmt = select(Company).order_by(Company.company_kana)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Company.company_name.like(like),
                Company.company_kana.like(like),
                Company.contact_email.like(like),
            )
        )
    out = []
    for company in s.scalars(stmt):
        n = (
            s.scalar(
                select(func.count())
                .select_from(Application)
                .where(Application.company_id == company.id)
            )
            or 0
        )
        out.append((company, n))
    return out


def roster_rows(s: Session, course_id) -> list[roster.Row]:
    stmt = (
        select(Application.application_no, Application.company_name, Attendee)
        .join(Attendee, Attendee.application_id == Application.id)
        .where(
            Application.course_id == course_id,
            Application.status == "confirmed",
        )
    )
    return [
        roster.Row(
            application_no=no,
            company_name=company,
            name=att.name,
            kana=att.kana,
            location=att.location,
        )
        for no, company, att in s.execute(stmt)
    ]


def ledger_rows(s: Session, year: int) -> list[ledger.Row]:
    """年度(4月起点)内に開催日をもつ講座の実績(draft は含めない)。"""
    start = datetime(year, 4, 1, tzinfo=JST)
    end = datetime(year + 1, 4, 1, tzinfo=JST)
    cat = {c.id: c.name for c in categories(s)}
    out = []
    for course in s.scalars(
        select(Course)
        .where(
            Course.starts_at >= start,
            Course.starts_at < end,
            Course.status != "draft",
        )
        .order_by(Course.starts_at)
    ):
        n_att = (
            s.scalar(
                select(func.count())
                .select_from(Attendee)
                .join(Application, Attendee.application_id == Application.id)
                .where(
                    Application.course_id == course.id,
                    Application.status == "confirmed",
                )
            )
            or 0
        )
        out.append(
            ledger.Row(
                title=course.title,
                category=cat.get(course.category_id, ""),
                starts_at=course.starts_at,
                status=course.status,
                applications=app_count(s, course.id),
                attendees=n_att,
                attendance=course.attendance_count,
            )
        )
    return out


def mails_for_course(s: Session, course_id) -> list[Mail]:
    return list(
        s.scalars(
            select(Mail)
            .where(Mail.course_id == course_id)
            .order_by(Mail.sent_at.desc())
        )
    )


def staff_list(s: Session) -> list[StaffRow]:
    return list(s.scalars(select(StaffRow).order_by(StaffRow.created_at)))


def staff_role(s: Session, staff_id: str) -> str | None:
    row = s.get(StaffRow, staff_id)
    return row.role if row else None

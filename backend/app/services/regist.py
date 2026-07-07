"""申込の登録(3経路共通の合流点)。

parse.FormData を受け取り、講座状態の検証(募集状態・期限・参加場所の
提供有無・会場定員)→ companies の upsert(事前登録)→ 採番 →
applications+attendees の登録を行う。検証で弾く場合は Rejected を送出し、
issues は申込者への自動返信文にそのまま使える日本語とする。
受領メールの送信・コミットは呼び出し側(mailin / docs callback)が行う。
"""

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Application, Attendee, Category, Company, Course
from app.services import no
from app.services.forms import LOC_JA
from app.services.parse import Entrant, FormData

_RETRY = 5  # 採番の UNIQUE 衝突リトライ回数


class Rejected(Exception):
    """講座の状態による受付不可。issues は申込者向けの日本語文。"""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__(" / ".join(issues))


def offered(course: Course) -> set[str]:
    """講座が提供する参加場所(DB の location 値)。"""
    locs = set()
    if course.allow_venue:
        locs.add("venue")
    if course.allow_online:
        locs.add("online")
    if course.allow_satellite:
        locs.add("satellite")
    return locs


def check(
    course: Course,
    entrants: Iterable[Entrant],
    venue_taken: int,
    at: datetime,
) -> list[str]:
    """講座の状態に依存する検証。DB を触らない(登録と画面側で共用できる)。"""
    issues: list[str] = []
    if course.status != "open":
        issues.append("この講座は募集を終了しています")
    elif at > course.apply_deadline:
        issues.append("申込期限を過ぎています")
    entrants = list(entrants)
    for loc in sorted({e.loc for e in entrants} - offered(course)):
        issues.append(f"この講座では「{LOC_JA[loc]}」での参加はご用意がありません")
    if course.capacity_venue is not None:
        new = sum(1 for e in entrants if e.loc == "venue")
        if new and venue_taken + new > course.capacity_venue:
            issues.append(
                "会場の定員に達したため、会場での参加はお受けできません"
                + (
                    "(オンラインでの参加をご検討ください)"
                    if course.allow_online
                    else ""
                )
            )
    return issues


def venue_taken(session: Session, course_id) -> int:
    """受付済み申込の会場参加者数(定員判定用)。"""
    return (
        session.scalar(
            select(func.count())
            .select_from(Attendee)
            .join(Application, Attendee.application_id == Application.id)
            .where(
                Application.course_id == course_id,
                Application.status == "confirmed",
                Attendee.location == "venue",
            )
        )
        or 0
    )


def _upsert_company(session: Session, form: FormData) -> Company:
    """初回=事前登録、以後は最新情報に更新(引き当てキーは担当者メール)。"""
    company = session.scalar(
        select(Company).where(Company.contact_email == form.contact_email)
    )
    if company is None:
        company = Company(contact_email=form.contact_email)
        session.add(company)
    company.company_name = form.company_name
    company.company_kana = form.company_kana
    company.contact_name = form.contact_name
    company.contact_kana = form.contact_kana
    company.postal_code = form.postal_code
    company.address = form.address
    company.tel = form.tel
    company.fax = form.fax
    session.flush()
    return company


def regist(
    session: Session,
    form: FormData,
    source: str,
    received_file: str | None = None,
    at: datetime | None = None,
) -> Application:
    """申込を登録する。成功で Application を返す(受領メールは呼び出し側)。"""
    at = at or datetime.now(UTC)
    course = session.get(Course, form.course_id)
    if course is None:
        raise Rejected(
            [
                "申込様式の講座情報が確認できませんでした。"
                "講座ページの最新の様式をご利用ください"
            ]
        )
    issues = check(course, form.entrants, venue_taken(session, course.id), at)
    if issues:
        raise Rejected(issues)

    company = _upsert_company(session, form)
    cat_slug = session.scalar(
        select(Category.slug).where(Category.id == course.category_id)
    )

    application = None
    for attempt in range(_RETRY):
        no_str, year, seq = no.next_no(session, at, code=cat_slug)
        application = Application(
            course_id=course.id,
            company_id=company.id,
            application_no=no_str,
            app_year=year,
            app_seq=seq,
            company_name=form.company_name,
            company_kana=form.company_kana,
            contact_name=form.contact_name,
            contact_kana=form.contact_kana,
            contact_email=form.contact_email,
            postal_code=form.postal_code,
            address=form.address,
            tel=form.tel,
            fax=form.fax,
            status="confirmed",
            source=source,
            received_file=received_file,
        )
        try:
            with session.begin_nested():
                session.add(application)
                session.flush()
            break
        except IntegrityError:
            if attempt == _RETRY - 1:
                raise

    for i, e in enumerate(form.entrants, start=1):
        session.add(
            Attendee(
                application_id=application.id,
                name=e.name,
                kana=e.kana,
                title_role=e.role,
                email=e.email,
                location=e.loc,
                sort_order=i,
            )
        )
    session.flush()
    return application

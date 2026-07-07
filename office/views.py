"""事務局アプリの各画面(Flet)。

各ビューは build_*(ctx) -> ft.Control。DB は1操作=1セッション。
DB・IMAP に届かないときは画面内にエラーを出す(アプリは落とさない)。
"""

import email
import email.policy
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import flet as ft
from app.core.config import Settings
from app.models import Course, Mail
from app.models import Staff as StaffRow
from app.services import ledger, mail, mailin, regist, roster, sitegen
from app.services.forms import JST, LOC_JA, jst
from app.services.parse import Entrant, FormData
from sqlalchemy.orm import Session

from office import queries
from office.auth import StaffId


@dataclass
class Ctx:
    page: ft.Page
    db: Callable[[], Session]  # sessionmaker
    cfg: Settings
    staff: StaffId
    mailer: mail.Mailer


# ---- 共通部品 ----


def snack(page: ft.Page, text: str) -> None:
    page.open(ft.SnackBar(ft.Text(text)))


def confirm(page: ft.Page, text: str, on_yes: Callable[[], None]) -> None:
    def yes(_):
        page.close(dlg)
        on_yes()

    dlg = ft.AlertDialog(
        title=ft.Text("確認"),
        content=ft.Text(text),
        actions=[
            ft.TextButton("やめる", on_click=lambda _: page.close(dlg)),
            ft.FilledButton("実行する", on_click=yes),
        ],
    )
    page.open(dlg)


def guarded(build: Callable[[], ft.Control]) -> ft.Control:
    """DB 未接続などで画面全体が死なないための番。"""
    try:
        return build()
    except Exception as e:  # noqa: BLE001 - 接続失敗など何が来ても画面に出す
        return ft.Column(
            [
                ft.Text("データに接続できません", weight=ft.FontWeight.BOLD),
                ft.Text(str(e), selectable=True),
            ]
        )


def parse_dt(value: str) -> datetime | None:
    """「2026-09-01 13:30」形式(JST)。空は None。"""
    value = value.strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=JST)


def fmt_dt(dt: datetime | None) -> str:
    return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M") if dt else ""


def regen_site(s: Session, cfg: Settings) -> None:
    sitegen.build_site(
        queries.courses(s),
        queries.categories(s),
        cfg.site_out,
        base_url=cfg.site_base_url,
        submit_addr=cfg.submit_addr,
        api_base=cfg.api_base_url,
    )


def course_dd(s: Session, on_change, status: str | None = None) -> ft.Dropdown:
    return ft.Dropdown(
        label="講座",
        options=[
            ft.dropdown.Option(str(c.id), f"{c.title}({jst(c.starts_at)})")
            for c in queries.courses(s, status)
        ],
        on_change=on_change,
        width=520,
    )


# ---- ダッシュボード ----


def build_dashboard(ctx: Ctx) -> ft.Control:
    def inner():
        with ctx.db() as s:
            open_rows = [
                (c.title, queries.app_count(s, c.id), queries.venue_left(s, c))
                for c in queries.courses(s, "open")
            ]
            recent = [
                (a.application_no, title, a.company_name, a.source)
                for a, title in queries.recent_apps(s)
            ]
        return ft.Column(
            [
                ft.Text("募集中の講座", weight=ft.FontWeight.BOLD),
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("講座")),
                        ft.DataColumn(ft.Text("申込数"), numeric=True),
                        ft.DataColumn(ft.Text("会場残席")),
                    ],
                    rows=[
                        ft.DataRow(cells=[ft.DataCell(ft.Text(str(v))) for v in row])
                        for row in open_rows
                    ],
                ),
                ft.Divider(),
                ft.Text("直近の申込", weight=ft.FontWeight.BOLD),
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("申込番号")),
                        ft.DataColumn(ft.Text("講座")),
                        ft.DataColumn(ft.Text("企業")),
                        ft.DataColumn(ft.Text("経路")),
                    ],
                    rows=[
                        ft.DataRow(cells=[ft.DataCell(ft.Text(str(v))) for v in row])
                        for row in recent
                    ],
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )

    return guarded(inner)


# ---- 講座管理 ----


def build_courses(ctx: Ctx) -> ft.Control:
    holder = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO)

    def show_list():
        def inner():
            with ctx.db() as s:
                cats = {c.id: c.name for c in queries.categories(s)}
                rows = []
                for c in queries.courses(s):
                    cid = c.id
                    rows.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(c.title)),
                                ft.DataCell(ft.Text(cats.get(c.category_id, ""))),
                                ft.DataCell(ft.Text(jst(c.starts_at))),
                                ft.DataCell(ft.Text(c.status)),
                                ft.DataCell(
                                    ft.TextButton(
                                        "編集",
                                        on_click=lambda _, cid=cid: show_form(cid),
                                    )
                                ),
                            ]
                        )
                    )
            return ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("講座管理", weight=ft.FontWeight.BOLD),
                            ft.FilledButton(
                                "新規作成", on_click=lambda _: show_form(None)
                            ),
                        ]
                    ),
                    ft.DataTable(
                        columns=[
                            ft.DataColumn(ft.Text(h))
                            for h in ("講座名", "分類", "開催日", "状態", "")
                        ],
                        rows=rows,
                    ),
                ]
            )

        holder.controls = [guarded(inner)]
        ctx.page.update()

    def show_form(course_id):
        holder.controls = [guarded(lambda: course_form(ctx, course_id, show_list))]
        ctx.page.update()

    show_list()
    return holder


def course_form(ctx: Ctx, course_id, on_done) -> ft.Control:
    with ctx.db() as s:
        course = s.get(Course, course_id) if course_id else None
        cats = queries.categories(s)

    def val(getter, default=""):
        return getter(course) if course else default

    f_title = ft.TextField(label="講座名", value=val(lambda c: c.title), width=520)
    f_cat = ft.Dropdown(
        label="分類",
        options=[ft.dropdown.Option(str(c.id), c.name) for c in cats],
        value=str(val(lambda c: c.category_id, "")),
        width=250,
    )
    f_summary = ft.TextField(
        label="一覧用の一言", value=val(lambda c: c.summary) or "", width=520
    )
    f_desc = ft.TextField(
        label="概要(講師紹介・内容)",
        value=val(lambda c: c.description) or "",
        multiline=True,
        min_lines=4,
        width=520,
    )
    f_starts = ft.TextField(
        label="開催日時(2026-09-01 13:30)",
        value=fmt_dt(val(lambda c: c.starts_at, None)),
        width=250,
    )
    f_ends = ft.TextField(
        label="終了(任意)", value=fmt_dt(val(lambda c: c.ends_at, None)), width=250
    )
    f_deadline = ft.TextField(
        label="申込期限", value=fmt_dt(val(lambda c: c.apply_deadline, None)), width=250
    )
    f_venue = ft.TextField(
        label="会場(名称・住所)", value=val(lambda c: c.venue_note) or "", width=520
    )
    f_allow_v = ft.Checkbox(
        label="会場", value=bool(val(lambda c: c.allow_venue, True))
    )
    f_allow_o = ft.Checkbox(
        label="オンライン", value=bool(val(lambda c: c.allow_online, False))
    )
    f_allow_s = ft.Checkbox(
        label="サテライト", value=bool(val(lambda c: c.allow_satellite, False))
    )
    f_sat = ft.TextField(
        label="サテライト会場名", value=val(lambda c: c.satellite_note) or "", width=250
    )
    f_cap = ft.TextField(
        label="会場定員(空=なし)",
        value=str(val(lambda c: c.capacity_venue, "") or ""),
        width=160,
    )
    f_fee = ft.TextField(
        label="受講料", value=val(lambda c: c.fee_note, "無料"), width=250
    )
    f_flyer = ft.TextField(
        label="チラシPDFのパス", value=val(lambda c: c.flyer_path) or "", width=520
    )
    f_online_note = ft.TextField(
        label="受講方法の定型文",
        value=val(lambda c: c.online_note) or "",
        multiline=True,
        min_lines=2,
        width=520,
    )
    f_meeting = ft.TextField(
        label="配信URL(公開されません)",
        value=val(lambda c: c.meeting_url) or "",
        width=430,
    )

    def gen_url(_):
        f_meeting.value = f"{ctx.cfg.jitsi_base}/{secrets.token_urlsafe(9)}"
        ctx.page.update()

    status = val(lambda c: c.status, "draft")

    def save(new_status: str | None):
        def doit():
            with ctx.db() as s:
                row = s.get(Course, course_id) if course_id else Course()
                row.title = f_title.value.strip()
                row.category_id = int(f_cat.value)
                row.summary = f_summary.value.strip() or None
                row.description = f_desc.value.strip() or None
                row.starts_at = parse_dt(f_starts.value)
                row.ends_at = parse_dt(f_ends.value)
                row.apply_deadline = parse_dt(f_deadline.value)
                row.venue_note = f_venue.value.strip() or None
                row.allow_venue = f_allow_v.value
                row.allow_online = f_allow_o.value
                row.allow_satellite = f_allow_s.value
                row.satellite_note = f_sat.value.strip() or None
                row.capacity_venue = int(f_cap.value) if f_cap.value.strip() else None
                row.fee_note = f_fee.value.strip() or "無料"
                row.flyer_path = f_flyer.value.strip() or None
                row.online_note = f_online_note.value.strip() or None
                row.meeting_url = f_meeting.value.strip() or None
                if new_status:
                    row.status = new_status
                if not course_id:
                    row.created_by = _staff_fk(s, ctx)
                    s.add(row)
                s.commit()
                regen_site(s, ctx.cfg)
            snack(ctx.page, "保存して静的サイトを再生成しました")
            on_done()

        try:
            doit()
        except Exception as e:  # noqa: BLE001 - 入力不備・DB断を画面に出す
            snack(ctx.page, f"保存できません: {e}")

    status_buttons = ft.Row(
        [
            ft.Text(f"状態: {status}"),
            ft.OutlinedButton("募集開始", on_click=lambda _: save("open")),
            ft.OutlinedButton("締切", on_click=lambda _: save("closed")),
            ft.OutlinedButton("開催済みへ", on_click=lambda _: save("finished")),
        ]
    )
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text(
                        "講座の編集" if course_id else "講座の新規作成",
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.TextButton("一覧へ戻る", on_click=lambda _: on_done()),
                ]
            ),
            f_title,
            ft.Row([f_cat, f_fee]),
            f_summary,
            f_desc,
            ft.Row([f_starts, f_ends, f_deadline]),
            f_venue,
            ft.Row([f_allow_v, f_allow_o, f_allow_s, f_sat]),
            ft.Row([f_cap]),
            f_flyer,
            f_online_note,
            ft.Row([f_meeting, ft.OutlinedButton("自動生成", on_click=gen_url)]),
            ft.Row([ft.FilledButton("保存", on_click=lambda _: save(None))]),
            status_buttons,
        ],
        scroll=ft.ScrollMode.AUTO,
    )


def _staff_fk(s: Session, ctx: Ctx) -> str | None:
    """staff 表に居る操作者のみ FK を張る(スタブ認証では None)。"""
    return ctx.staff.id if s.get(StaffRow, ctx.staff.id) else None


# ---- 申込一覧 ----


def build_apps(ctx: Ctx) -> ft.Control:
    result = ft.Column()
    state = {"course_id": None}

    def load(_=None):
        if not state["course_id"]:
            return

        def inner():
            with ctx.db() as s:
                counts = queries.loc_counts(s, state["course_id"])
                tabs = []
                for st, label in (
                    ("confirmed", "受付済み"),
                    ("cancelled", "キャンセル"),
                ):
                    rows = []
                    for a in queries.apps_for_course(s, state["course_id"], st):
                        atts = queries.attendees_of(s, a.id)
                        names = "、".join(
                            f"{x.name}({LOC_JA[x.location]})" for x in atts
                        )
                        cell_action = (
                            ft.Row(
                                [
                                    ft.TextButton(
                                        "受領メール再送",
                                        on_click=lambda _, no=a.application_no: resend(
                                            no
                                        ),
                                    ),
                                    ft.TextButton(
                                        "キャンセル",
                                        on_click=lambda _, no=a.application_no: cancel(
                                            no
                                        ),
                                    ),
                                ]
                            )
                            if st == "confirmed"
                            else ft.Text("")
                        )
                        rows.append(
                            ft.DataRow(
                                cells=[
                                    ft.DataCell(ft.Text(a.application_no)),
                                    ft.DataCell(ft.Text(a.company_name)),
                                    ft.DataCell(ft.Text(a.contact_name)),
                                    ft.DataCell(ft.Text(names)),
                                    ft.DataCell(ft.Text(a.source)),
                                    ft.DataCell(ft.Text(a.received_file or "")),
                                    ft.DataCell(cell_action),
                                ]
                            )
                        )
                    tabs.append(
                        ft.Tab(
                            text=f"{label}({len(rows)})",
                            content=ft.Column(
                                [
                                    ft.DataTable(
                                        columns=[
                                            ft.DataColumn(ft.Text(h))
                                            for h in (
                                                "申込番号",
                                                "企業",
                                                "担当者",
                                                "受講者",
                                                "経路",
                                                "原本",
                                                "",
                                            )
                                        ],
                                        rows=rows,
                                    )
                                ],
                                scroll=ft.ScrollMode.AUTO,
                            ),
                        )
                    )
            summary = (
                " / ".join(f"{LOC_JA[k]} {v}名" for k, v in sorted(counts.items()))
                or "受講者なし"
            )
            return ft.Column(
                [
                    ft.Text(f"参加場所別(受付済み): {summary}"),
                    ft.Tabs(tabs=tabs, expand=False),
                ]
            )

        result.controls = [guarded(inner)]
        ctx.page.update()

    def cancel(no: str):
        def doit():
            try:
                with ctx.db() as s:
                    a = queries.find_app(s, no)
                    a.status = "cancelled"
                    course = s.get(Course, a.course_id)
                    subject, body = mail.cancelled(a, course)
                    s.commit()
                ctx.mailer.send(a.contact_email, subject, body)
                snack(ctx.page, f"{no} をキャンセルし、受付メールを送りました")
            except Exception as e:  # noqa: BLE001
                snack(ctx.page, f"処理できません: {e}")
            load()

        confirm(ctx.page, f"申込 {no} をキャンセルしますか?", doit)

    def resend(no: str):
        """確認メールの不達に備えた再送(01 非機能要件)。"""
        try:
            with ctx.db() as s:
                a = queries.find_app(s, no)
                course = s.get(Course, a.course_id)
                entrants = tuple(
                    Entrant(
                        name=x.name,
                        kana=x.kana,
                        role=x.title_role,
                        email=x.email,
                        loc=x.location,
                    )
                    for x in queries.attendees_of(s, a.id)
                )
                subject, body = mail.receipt(a, course, entrants)
                to = a.contact_email
            ctx.mailer.send(to, subject, body)
            snack(ctx.page, f"{no} の受領メールを {to} へ再送しました")
        except Exception as e:  # noqa: BLE001
            snack(ctx.page, f"再送できません: {e}")

    def on_course(e):
        state["course_id"] = e.control.value
        load()

    f_no = ft.TextField(label="申込番号で検索", width=200)

    def search(_):
        def inner():
            with ctx.db() as s:
                a = queries.find_app(s, f_no.value)
                if a is None:
                    return ft.Text("見つかりません")
                atts = queries.attendees_of(s, a.id)
                names = "、".join(f"{x.name}({LOC_JA[x.location]})" for x in atts)
                course = s.get(Course, a.course_id)
                return ft.Text(
                    f"{a.application_no}: {course.title} / {a.company_name} / "
                    f"{names} / {a.status}"
                )

        result.controls = [guarded(inner)]
        ctx.page.update()

    def dd():
        with ctx.db() as s:
            return course_dd(s, on_course)

    return ft.Column(
        [
            ft.Text("申込一覧", weight=ft.FontWeight.BOLD),
            ft.Row([guarded(dd), f_no, ft.OutlinedButton("検索", on_click=search)]),
            result,
        ],
        scroll=ft.ScrollMode.AUTO,
    )


# ---- 未処理受信 ----


def build_inbox(ctx: Ctx) -> ft.Control:
    holder = ft.Column()

    def load(_=None):
        def inner():
            box = mailin.ImapBox(ctx.cfg)
            try:
                box.select(ctx.cfg.imap_pending)
                items = box.fetch_all()
                rows = []
                for uid, raw in items:
                    msg = email.message_from_bytes(raw, policy=email.policy.default)
                    body = mailin.body_text(msg)[:200]

                    def mover(folder_attr, uid=uid):
                        def doit(_):
                            b = mailin.ImapBox(ctx.cfg)
                            try:
                                b.select(ctx.cfg.imap_pending)
                                b.move(uid, getattr(ctx.cfg, folder_attr))
                            finally:
                                b.close()
                            snack(ctx.page, "移動しました")
                            load()

                        return doit

                    rows.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(str(msg.get("Date", "")))),
                                ft.DataCell(ft.Text(str(msg.get("From", "")))),
                                ft.DataCell(ft.Text(str(msg.get("Subject", "")))),
                                ft.DataCell(ft.Text(body)),
                                ft.DataCell(
                                    ft.Row(
                                        [
                                            ft.TextButton(
                                                "処理済みへ",
                                                on_click=mover("imap_done"),
                                            ),
                                            ft.TextButton(
                                                "差戻しへ",
                                                on_click=mover("imap_returned"),
                                            ),
                                        ]
                                    )
                                ),
                            ]
                        )
                    )
            finally:
                box.close()
            return ft.Column(
                [
                    ft.Text(
                        "読み取れなかった申込メール。内容を確認して「代行入力」で"
                        "登録し、処理済みへ移してください。FAX・紙もここではなく"
                        "代行入力から直接登録します。"
                    ),
                    ft.DataTable(
                        columns=[
                            ft.DataColumn(ft.Text(h))
                            for h in ("受信日時", "差出人", "件名", "本文(冒頭)", "")
                        ],
                        rows=rows,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
            )

        holder.controls = [guarded(inner)]
        ctx.page.update()

    load()
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text("未処理受信", weight=ft.FontWeight.BOLD),
                    ft.OutlinedButton("再読込", on_click=load),
                ]
            ),
            holder,
        ],
        scroll=ft.ScrollMode.AUTO,
    )


# ---- 代行入力(FAX・紙・未処理メール) ----


def build_entry(ctx: Ctx) -> ft.Control:
    state = {"course_id": None}

    def on_course(e):
        state["course_id"] = e.control.value

    def dd():
        with ctx.db() as s:
            return course_dd(s, on_course, status="open")

    f = {
        name: ft.TextField(label=label, width=250)
        for name, label in (
            ("company_name", "企業・団体名"),
            ("company_kana", "フリガナ"),
            ("postal_code", "郵便番号"),
            ("address", "所在地"),
            ("tel", "電話番号"),
            ("fax", "FAX(任意)"),
            ("contact_name", "ご担当者名"),
            ("contact_kana", "フリガナ(担当者)"),
            ("contact_email", "メールアドレス"),
        )
    }
    entrant_rows = []
    for i in (1, 2, 3):
        entrant_rows.append(
            {
                "name": ft.TextField(label=f"受講者{i} 氏名", width=160),
                "kana": ft.TextField(label="フリガナ", width=160),
                "role": ft.TextField(label="所属・役職", width=160),
                "email": ft.TextField(label="メール", width=200),
                "loc": ft.Dropdown(
                    label="参加場所",
                    options=[
                        ft.dropdown.Option(code, label)
                        for code, label in LOC_JA.items()
                    ],
                    width=140,
                ),
            }
        )

    def submit(_):
        try:
            entrants = tuple(
                Entrant(
                    name=r["name"].value.strip(),
                    kana=r["kana"].value.strip(),
                    role=r["role"].value.strip(),
                    email=r["email"].value.strip() or f["contact_email"].value.strip(),
                    loc=r["loc"].value,
                )
                for r in entrant_rows
                if r["name"].value.strip()
            )
            form = FormData(
                course_id=uuid.UUID(state["course_id"]),
                form_ver=0,  # 代行入力(様式経由でない)
                company_name=f["company_name"].value.strip(),
                company_kana=f["company_kana"].value.strip(),
                contact_name=f["contact_name"].value.strip(),
                contact_kana=f["contact_kana"].value.strip(),
                contact_email=f["contact_email"].value.strip(),
                postal_code=f["postal_code"].value.strip(),
                address=f["address"].value.strip(),
                tel=f["tel"].value.strip(),
                fax=f["fax"].value.strip() or None,
                entrants=entrants,
            )
            with ctx.db() as s:
                application = regist.regist(s, form, source="staff")
                no = application.application_no
                course = s.get(Course, form.course_id)
                subject, body = mail.receipt(application, course, entrants)
                s.commit()
            if form.contact_email:
                ctx.mailer.send(form.contact_email, subject, body)
            snack(ctx.page, f"登録しました(申込番号 {no})")
        except regist.Rejected as e:
            snack(ctx.page, f"受付できません: {' / '.join(e.issues)}")
        except Exception as e:  # noqa: BLE001
            snack(ctx.page, f"登録できません: {e}")

    return ft.Column(
        [
            ft.Text("代行入力(FAX・紙・未処理メール)", weight=ft.FontWeight.BOLD),
            guarded(dd),
            ft.Row([f["company_kana"], f["company_name"]]),
            ft.Row([f["postal_code"], f["address"]]),
            ft.Row([f["tel"], f["fax"]]),
            ft.Row([f["contact_kana"], f["contact_name"], f["contact_email"]]),
            *[ft.Row(list(r.values())) for r in entrant_rows],
            ft.FilledButton("登録(受領メール送信)", on_click=submit),
        ],
        scroll=ft.ScrollMode.AUTO,
    )


# ---- 企業一覧 ----


def build_companies(ctx: Ctx) -> ft.Control:
    holder = ft.Column()
    f_q = ft.TextField(label="検索(名称・カナ・メール)", width=300)

    def load(_=None):
        def inner():
            with ctx.db() as s:
                rows = []
                for company, n in queries.companies(s, f_q.value.strip()):
                    rows.append(
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(company.company_name)),
                                ft.DataCell(ft.Text(company.contact_name)),
                                ft.DataCell(ft.Text(company.contact_email)),
                                ft.DataCell(ft.Text(company.tel)),
                                ft.DataCell(ft.Text(str(n))),
                            ]
                        )
                    )
            return ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text(h))
                    for h in ("企業・団体名", "担当者", "メール", "電話", "申込数")
                ],
                rows=rows,
            )

        holder.controls = [guarded(inner)]
        ctx.page.update()

    load()
    return ft.Column(
        [
            ft.Text(
                "企業一覧(事前登録済み。申込数があれば簡易メール可)",
                weight=ft.FontWeight.BOLD,
            ),
            ft.Row([f_q, ft.OutlinedButton("検索", on_click=load)]),
            holder,
        ],
        scroll=ft.ScrollMode.AUTO,
    )


# ---- 一斉送信 ----


def build_bulk(ctx: Ctx) -> ft.Control:
    state = {"course_id": None}
    history = ft.Column()

    f_target = ft.RadioGroup(
        value="all",
        content=ft.Row(
            [
                ft.Radio(value="all", label="全員"),
                ft.Radio(value="venue", label="会場"),
                ft.Radio(value="online", label="オンライン"),
                ft.Radio(value="satellite", label="サテライト"),
            ]
        ),
    )
    f_subject = ft.TextField(label="件名", width=520)
    f_body = ft.TextField(label="本文", multiline=True, min_lines=8, width=520)

    def load_history():
        def inner():
            if not state["course_id"]:
                return ft.Text("")
            with ctx.db() as s:
                rows = [
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(jst(m.sent_at))),
                            ft.DataCell(ft.Text(m.subject)),
                            ft.DataCell(ft.Text(m.target)),
                            ft.DataCell(ft.Text(str(m.recipient_count))),
                        ]
                    )
                    for m in queries.mails_for_course(s, state["course_id"])
                ]
            return ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text(h))
                    for h in ("送信日時", "件名", "宛先", "通数")
                ],
                rows=rows,
            )

        history.controls = [guarded(inner)]
        ctx.page.update()

    def on_course(e):
        state["course_id"] = e.control.value
        load_history()

    def insert_url(_):
        try:
            with ctx.db() as s:
                course = s.get(Course, uuid.UUID(state["course_id"]))
                url = course.meeting_url or "(配信URL未設定)"
            f_body.value = (f_body.value or "") + f"\n配信URL: {url}\n"
            ctx.page.update()
        except Exception as e:  # noqa: BLE001
            snack(ctx.page, f"挿入できません: {e}")

    def send(_):
        if not state["course_id"] or not f_subject.value.strip():
            snack(ctx.page, "講座と件名を入れてください")
            return
        try:
            with ctx.db() as s:
                addrs = queries.recipients(s, state["course_id"], f_target.value)
        except Exception as e:  # noqa: BLE001
            snack(ctx.page, f"宛先を取得できません: {e}")
            return
        if not addrs:
            snack(ctx.page, "宛先がありません")
            return

        def doit():
            try:
                n = mail.send_bulk(ctx.mailer, addrs, f_subject.value, f_body.value)
                with ctx.db() as s:
                    s.add(
                        Mail(
                            course_id=uuid.UUID(state["course_id"]),
                            subject=f_subject.value,
                            body=f_body.value,
                            target=f_target.value,
                            recipient_count=n,
                            sent_by=_staff_fk(s, ctx),
                        )
                    )
                    s.commit()
                snack(ctx.page, f"{n}件に送信し、記録しました")
                load_history()
            except Exception as e:  # noqa: BLE001
                snack(ctx.page, f"送信できません: {e}")

        confirm(ctx.page, f"{len(addrs)}件に送信します。よろしいですか?", doit)

    def dd():
        with ctx.db() as s:
            return course_dd(s, on_course)

    return ft.Column(
        [
            ft.Text(
                "一斉送信(確定受講者のみ。送信記録が残ります)",
                weight=ft.FontWeight.BOLD,
            ),
            guarded(dd),
            f_target,
            f_subject,
            f_body,
            ft.Row(
                [
                    ft.OutlinedButton("配信URLを挿入", on_click=insert_url),
                    ft.FilledButton("送信", on_click=send),
                ]
            ),
            ft.Text("送信履歴", weight=ft.FontWeight.BOLD),
            history,
        ],
        scroll=ft.ScrollMode.AUTO,
    )


# ---- 名簿・実績 ----


def build_reports(ctx: Ctx) -> ft.Control:
    state = {"course_id": None}
    f_att = ft.TextField(label="出席者数", width=120)
    info = ft.Text("")

    def on_course(e):
        state["course_id"] = e.control.value
        with ctx.db() as s:
            course = s.get(Course, uuid.UUID(state["course_id"]))
            f_att.value = (
                str(course.attendance_count)
                if course.attendance_count is not None
                else ""
            )
            info.value = f"受付済み {queries.app_count(s, course.id)}件"
        ctx.page.update()

    def export_roster(_):
        if not state["course_id"]:
            snack(ctx.page, "講座を選んでください")
            return
        try:
            with ctx.db() as s:
                cid = uuid.UUID(state["course_id"])
                course = s.get(Course, cid)
                rows = queries.roster_rows(s, cid)
                wb = roster.build(course, rows)
            out = Path(ctx.cfg.output_dir)
            out.mkdir(parents=True, exist_ok=True)
            path = out / f"名簿_{course.title}.xlsx"
            wb.save(path)
            snack(ctx.page, f"出力しました: {path}({len(rows)}名)")
        except Exception as e:  # noqa: BLE001
            snack(ctx.page, f"出力できません: {e}")

    def save_att(_):
        try:
            with ctx.db() as s:
                course = s.get(Course, uuid.UUID(state["course_id"]))
                course.attendance_count = (
                    int(f_att.value) if f_att.value.strip() else None
                )
                s.commit()
            snack(ctx.page, "出席者数を保存しました(実績台帳に反映されます)")
        except Exception as e:  # noqa: BLE001
            snack(ctx.page, f"保存できません: {e}")

    def dd():
        with ctx.db() as s:
            return course_dd(s, on_course)

    return ft.Column(
        [
            ft.Text("名簿・実績", weight=ft.FontWeight.BOLD),
            guarded(dd),
            info,
            ft.Row(
                [
                    ft.FilledButton(
                        "当日名簿を xlsx 出力(印刷して受付で使用)",
                        on_click=export_roster,
                    )
                ]
            ),
            ft.Row([f_att, ft.OutlinedButton("出席者数を保存", on_click=save_att)]),
        ],
        scroll=ft.ScrollMode.AUTO,
    )


# ---- エクスポート ----


def build_export(ctx: Ctx) -> ft.Control:
    f_year = ft.TextField(
        label="年度", value=str(ledger.fiscal_year(datetime.now(tz=JST))), width=120
    )

    def export(kind: str):
        try:
            year = int(f_year.value)
            with ctx.db() as s:
                rows = queries.ledger_rows(s, year)
            out = Path(ctx.cfg.output_dir)
            out.mkdir(parents=True, exist_ok=True)
            if kind == "xlsx":
                path = out / f"実績台帳_{year}年度.xlsx"
                ledger.build(year, rows).save(path)
            else:
                path = out / f"実績台帳_{year}年度.csv"
                path.write_text(ledger.to_csv(year, rows), encoding="utf-8-sig")
            snack(ctx.page, f"出力しました: {path}({len(rows)}講座)")
        except Exception as e:  # noqa: BLE001
            snack(ctx.page, f"出力できません: {e}")

    return ft.Column(
        [
            ft.Text("年度実績台帳(事業報告の基礎資料)", weight=ft.FontWeight.BOLD),
            ft.Row(
                [
                    f_year,
                    ft.FilledButton("xlsx 出力", on_click=lambda _: export("xlsx")),
                    ft.OutlinedButton("CSV 出力", on_click=lambda _: export("csv")),
                ]
            ),
        ]
    )


# ---- スタッフ(admin) ----


def build_staff(ctx: Ctx) -> ft.Control:
    def role_of():
        with ctx.db() as s:
            return queries.staff_role(s, ctx.staff.id) or ctx.staff.role

    try:
        if role_of() != "admin":
            return ft.Text("この画面は admin のみ使えます")
    except Exception:  # noqa: BLE001 - DB断は下の guarded で表示される
        pass

    holder = ft.Column()
    f_id = ft.TextField(label="PocketBase ID", width=200)
    f_name = ft.TextField(label="表示名", width=200)
    f_dept = ft.TextField(label="担当部署名", width=200)
    f_role = ft.Dropdown(
        label="権限",
        options=[ft.dropdown.Option("staff"), ft.dropdown.Option("admin")],
        value="staff",
        width=120,
    )

    def load(_=None):
        def inner():
            with ctx.db() as s:
                rows = [
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(x.id)),
                            ft.DataCell(ft.Text(x.display_name)),
                            ft.DataCell(ft.Text(x.contact_label or "")),
                            ft.DataCell(ft.Text(x.role)),
                        ]
                    )
                    for x in queries.staff_list(s)
                ]
            return ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text(h))
                    for h in ("ID", "表示名", "担当部署", "権限")
                ],
                rows=rows,
            )

        holder.controls = [guarded(inner)]
        ctx.page.update()

    def add(_):
        try:
            with ctx.db() as s:
                s.add(
                    StaffRow(
                        id=f_id.value.strip(),
                        display_name=f_name.value.strip(),
                        contact_label=f_dept.value.strip() or None,
                        role=f_role.value,
                    )
                )
                s.commit()
            snack(ctx.page, "追加しました")
            load()
        except Exception as e:  # noqa: BLE001
            snack(ctx.page, f"追加できません: {e}")

    load()
    return ft.Column(
        [
            ft.Text("スタッフ管理", weight=ft.FontWeight.BOLD),
            ft.Row(
                [f_id, f_name, f_dept, f_role, ft.FilledButton("追加", on_click=add)]
            ),
            holder,
        ],
        scroll=ft.ScrollMode.AUTO,
    )

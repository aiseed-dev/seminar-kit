"""事務局アプリ(Flet)。機関内サーバーで `flet run --web office/main.py`。

DB 直結(backend の models / services を import)。ログインは操作者記録の
ため(開発はスタブ、本番は PocketBase — SEMINAR_AUTH=pocketbase)。
"""

import os

import flet as ft
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.services import mail

from office import auth, views

MENU = (
    ("ダッシュボード", ft.Icons.DASHBOARD, views.build_dashboard),
    ("講座管理", ft.Icons.SCHOOL, views.build_courses),
    ("申込一覧", ft.Icons.LIST_ALT, views.build_apps),
    ("未処理受信", ft.Icons.MARK_EMAIL_UNREAD, views.build_inbox),
    ("代行入力", ft.Icons.EDIT_NOTE, views.build_entry),
    ("企業一覧", ft.Icons.BUSINESS, views.build_companies),
    ("一斉送信", ft.Icons.SEND, views.build_bulk),
    ("名簿・実績", ft.Icons.FACT_CHECK, views.build_reports),
    ("エクスポート", ft.Icons.DOWNLOAD, views.build_export),
    ("スタッフ", ft.Icons.MANAGE_ACCOUNTS, views.build_staff),
)


def get_auth(cfg) -> auth.Auth:
    if os.environ.get("SEMINAR_AUTH") == "pocketbase":
        return auth.PocketBase(
            os.environ.get("SEMINAR_PB_URL", "http://localhost:8090")
        )
    return auth.Stub()


def main(page: ft.Page):
    page.title = "研修・セミナー事務局"
    cfg = get_settings()

    def start(staff: auth.StaffId):
        ctx = views.Ctx(
            page=page,
            db=get_sessionmaker(),
            cfg=cfg,
            staff=staff,
            mailer=mail.Smtp(cfg),
        )
        content = ft.Container(expand=True, padding=16)

        def show(i: int):
            content.content = MENU[i][2](ctx)
            page.update()

        rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            destinations=[
                ft.NavigationRailDestination(icon=icon, label=label)
                for label, icon, _ in MENU
            ],
            on_change=lambda e: show(e.control.selected_index),
        )
        page.clean()
        page.add(
            ft.Row(
                [rail, ft.VerticalDivider(width=1), content],
                expand=True,
            )
        )
        show(0)

    f_user = ft.TextField(label="ユーザー", width=280, autofocus=True)
    f_pass = ft.TextField(
        label="パスワード", width=280, password=True, can_reveal_password=True
    )
    msg = ft.Text("", color=ft.Colors.RED)

    def login(_):
        staff = get_auth(cfg).login(f_user.value.strip(), f_pass.value)
        if staff is None:
            msg.value = "ログインできません"
            page.update()
            return
        start(staff)

    f_pass.on_submit = login
    page.add(
        ft.Column(
            [
                ft.Text("研修・セミナー事務局", size=22, weight=ft.FontWeight.BOLD),
                f_user,
                f_pass,
                ft.FilledButton("ログイン", on_click=login),
                msg,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            expand=True,
        )
    )


if __name__ == "__main__":
    ft.run(main)

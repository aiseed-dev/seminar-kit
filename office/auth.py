"""スタッフ認証(操作者の記録のため)。

本番は PocketBase、開発はスタブ。差し替え点は Auth プロトコル。
PocketBase の実機結線・動作確認は Phase 5(SEMINAR_AUTH=pocketbase で切替)。
"""

import json
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StaffId:
    """ログインしたスタッフ(seminar.staff の id に対応)。"""

    id: str
    name: str
    role: str  # staff / admin


class Auth(Protocol):
    def login(self, user: str, password: str) -> StaffId | None: ...


class Stub:
    """開発用: 空でなければ誰でも admin で通す。本番では使わない。"""

    def login(self, user: str, password: str) -> StaffId | None:
        if user and password:
            return StaffId(id=user, name=user, role="admin")
        return None


class PocketBase:
    """PocketBase の users コレクションで認証する(role は staff 表で管理)。"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def login(self, user: str, password: str) -> StaffId | None:
        req = urllib.request.Request(
            f"{self.base_url}/api/collections/users/auth-with-password",
            data=json.dumps({"identity": user, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                record = json.load(res)["record"]
        except Exception:
            return None
        return StaffId(
            id=record["id"],
            name=record.get("name") or record.get("email", ""),
            role="staff",  # 権限は seminar.staff 側で引き直す(views 参照)
        )

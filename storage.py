"""Tiny JSON storage. Good enough for a demo; swap for SQLite/Postgres in production."""
import json
import os
import time
from typing import Any

import config


class Store:
    def __init__(self, path=config.DATA_FILE):
        self.path = path
        self.data: dict[str, Any] = {"users": {}, "locations": [], "pending": {}, "cert_counter": 0}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- users ----
    def user(self, tg_user) -> dict:
        uid = str(tg_user.id)
        u = self.data["users"].get(uid)
        if u is None:
            u = {
                "id": tg_user.id,
                "name": tg_user.full_name,
                "username": tg_user.username,
                "xp": 0,
                "done": [],
                "created": [],
                "achievements": [],
                "streak_first_try": 0,
                "invited_by": None,
                "invites": 0,
                "joined": int(time.time()),
                "cert_id": None,
            }
            self.data["users"][uid] = u
        else:
            u["name"] = tg_user.full_name
            u["username"] = tg_user.username
        return u

    def get_user(self, uid: int) -> dict | None:
        return self.data["users"].get(str(uid))

    def top(self, n: int = 10) -> list[dict]:
        return sorted(self.data["users"].values(), key=lambda u: u["xp"], reverse=True)[:n]

    def rank(self, uid: int) -> int:
        order = sorted(self.data["users"].values(), key=lambda u: u["xp"], reverse=True)
        for i, u in enumerate(order, 1):
            if u["id"] == uid:
                return i
        return len(order)

    def next_cert_number(self) -> int:
        self.data["cert_counter"] += 1
        return self.data["cert_counter"]


store = Store()

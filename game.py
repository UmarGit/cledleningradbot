"""Pure game logic (no Telegram calls) so it is easy to test and tweak."""
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import content as C
from storage import store


# ---------- locations ----------
def all_locations() -> list[dict]:
    return C.LOCATIONS + store.data["locations"]


def get_location(loc_id: str) -> dict | None:
    return next((l for l in all_locations() if l["id"] == loc_id), None)


def distance_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def human_distance(m: float) -> str:
    return f"{m:.0f} м" if m < 1000 else f"{m / 1000:.1f} км"


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


# ---------- answers ----------
def normalize(s: str) -> str:
    s = s.lower().replace("ё", "е")
    return re.sub(r"[^\w]+", " ", s).strip()


def check_input(task: dict, text: str) -> bool:
    given = normalize(text)
    return any(normalize(a) == given or normalize(a) in given.split() for a in task["answers"])


# ---------- levels & xp ----------
def level_of(xp: int) -> tuple[int, str, int | None]:
    """Returns (level number, name, xp needed for next level or None)."""
    idx = 0
    for i, (need, _) in enumerate(C.LEVELS):
        if xp >= need:
            idx = i
    nxt = C.LEVELS[idx + 1][0] if idx + 1 < len(C.LEVELS) else None
    return idx + 1, C.LEVELS[idx][1], nxt


def progress_bar(xp: int, width: int = 10) -> str:
    lvl, _, nxt = level_of(xp)
    if nxt is None:
        return "▰" * width
    cur = C.LEVELS[lvl - 1][0]
    filled = round((xp - cur) / (nxt - cur) * width)
    return "▰" * filled + "▱" * (width - filled)


def add_xp(user: dict, amount: int) -> tuple[int, bool]:
    """Adds XP; returns (new xp, level_up?)."""
    before = level_of(user["xp"])[0]
    user["xp"] = max(0, user["xp"] + amount)
    return user["xp"], level_of(user["xp"])[0] > before


def task_xp(base_share: int, attempts: int, seconds: float) -> tuple[int, list[str]]:
    """XP for one task + human-readable breakdown."""
    xp, notes = base_share, [f"+{base_share} за задание"]
    if attempts == 1:
        xp += C.XP_FIRST_TRY_BONUS
        notes.append(f"+{C.XP_FIRST_TRY_BONUS} с первой попытки")
    else:
        pen = min(C.XP_WRONG_PENALTY * (attempts - 1), base_share // 2)
        xp -= pen
        notes.append(f"−{pen} за ошибки")
    if seconds <= C.SPEED_SECONDS:
        xp += C.XP_SPEED_BONUS
        notes.append(f"+{C.XP_SPEED_BONUS} за скорость ⚡")
    return xp, notes


# ---------- achievements ----------
def grant(user: dict, key: str) -> bool:
    if key in user["achievements"]:
        return False
    user["achievements"].append(key)
    return True


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def after_task(user: dict, attempts: int, seconds: float, task_type: str) -> list[str]:
    new = []
    if attempts == 1 and task_type in ("input", "quiz"):
        user["streak_first_try"] += 1
    elif task_type in ("input", "quiz"):
        user["streak_first_try"] = 0
    if user["streak_first_try"] >= 3 and grant(user, "sniper"):
        new.append("sniper")
    if task_type in ("input", "quiz") and attempts == 1 and seconds <= C.SPEED_SECONDS and grant(user, "lightning"):
        new.append("lightning")
    if task_type == "voice" and grant(user, "polyglot"):
        new.append("polyglot")
    return new


def after_quest(user: dict) -> list[str]:
    new = []
    if len(user["done"]) >= 1 and grant(user, "first_trace"):
        new.append("first_trace")
    if len(user["done"]) >= 3 and grant(user, "explorer"):
        new.append("explorer")
    h = now_local().hour
    if (h >= 22 or h < 5) and grant(user, "night"):
        new.append("night")
    return new


def badge(key: str) -> str:
    e, name, _ = C.ACHIEVEMENTS[key]
    return f"{e} {name}"


# ---------- mock moderation ----------
def moderate(draft: dict) -> tuple[bool, list[str]]:
    """Returns (approved, list of check lines)."""
    checks, ok = [], True

    def line(passed: bool, text: str):
        nonlocal ok
        ok = ok and passed
        checks.append(("✅ " if passed else "❌ ") + text)

    line(bool(draft.get("photos")), "Есть фотографии")
    line(len(draft.get("desc", "")) >= 40, "Описание не короче 40 символов")
    text = normalize(" ".join([draft.get("title", ""), draft.get("desc", ""), draft.get("question", "")]))
    line(not any(w.strip(":/") in text for w in C.STOP_WORDS), "Без рекламы и ссылок")
    if draft.get("lat") is not None:
        near = [l for l in all_locations() if l.get("lat") is not None and distance_m(draft["lat"], draft["lon"], l["lat"], l["lon"]) < 150]
        line(not near, "Рядом ещё нет такого следа" if not near else f"Рядом уже есть «{near[0]['title']}»")
    else:
        checks.append("➖ Геолокация указана адресом (проверит куратор)")
    return ok, checks

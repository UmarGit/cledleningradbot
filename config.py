"""Settings, read from environment variables (or a .env file next to bot.py)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    env = BASE_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# Demo mode: shows a "I'm on the spot" button so the audience can play without travelling,
# and enables /demo (+XP boost) for everyone.
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"
# Comma-separated Telegram user ids with admin rights (/demo, /reset, manual moderation)
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
# "auto" = mock automatic moderation; "manual" = sent to admins with Approve / Reject buttons
MODERATION = os.getenv("MODERATION", "auto")
VISIT_RADIUS_M = int(os.getenv("VISIT_RADIUS_M", "300"))
CERT_MIN_XP = int(os.getenv("CERT_MIN_XP", "150"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
DATA_FILE = Path(os.getenv("DATA_FILE", str(BASE_DIR / "data" / "db.json")))
ASSETS = BASE_DIR / "assets"

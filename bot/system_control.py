"""Final production runtime controls."""
from __future__ import annotations

import os
import time

STARTED_AT = time.monotonic()
APP_VERSION = "47.0.0"

# Optional Render/environment switch. Admin controls below can change this at runtime.
MAINTENANCE_MODE = os.getenv("BOT_MAINTENANCE_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}


def is_maintenance() -> bool:
    return bool(MAINTENANCE_MODE)


def set_maintenance(enabled: bool) -> bool:
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = bool(enabled)
    return MAINTENANCE_MODE


def uptime_seconds() -> int:
    return max(0, int(time.monotonic() - STARTED_AT))


def format_uptime() -> str:
    seconds = uptime_seconds()
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)

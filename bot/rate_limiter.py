"""Per-user daily video quota with owner/admin overrides."""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("RATE_LIMIT_DB_PATH", str(DATA_DIR / "rate_limits.sqlite3")))
DEFAULT_LIMIT = int(os.getenv("DEFAULT_DAILY_VIDEO_LIMIT", "2").strip() or "2")
TIMEZONE = ZoneInfo(os.getenv("RATE_LIMIT_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata")


def _today() -> str:
    from datetime import datetime

    return datetime.now(TIMEZONE).date().isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_limits (
            user_id INTEGER PRIMARY KEY,
            daily_limit INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_usage (
            user_id INTEGER NOT NULL,
            usage_date TEXT NOT NULL,
            video_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, usage_date)
        );
        """
    )
    return connection


def _configured_limit(connection: sqlite3.Connection, user_id: int) -> int:
    # Active premium subscriptions take priority over the normal/admin daily limit.
    # Import lazily to avoid a module-import cycle.
    try:
        from bot.subscription import get_effective_limit
        subscription_limit = get_effective_limit(user_id)
        if subscription_limit is not None:
            return int(subscription_limit)
    except Exception:
        # Subscription status must never break the core quota system.
        pass

    row = connection.execute(
        "SELECT daily_limit FROM user_limits WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row["daily_limit"]) if row else DEFAULT_LIMIT


def get_status(user_id: int) -> dict[str, int | str]:
    with _connect() as connection:
        limit = _configured_limit(connection, user_id)
        today = _today()
        row = connection.execute(
            "SELECT video_count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
        used = int(row["video_count"]) if row else 0

    remaining = -1 if limit < 0 else max(limit - used, 0)
    return {
        "user_id": user_id,
        "date": today,
        "limit": limit,
        "used": used,
        "remaining": remaining,
    }


def set_limit(user_id: int, daily_limit: int) -> None:
    if daily_limit < -1:
        raise ValueError("Limit must be -1, 0, or a positive integer.")

    with _connect() as connection:
        connection.execute(
            "INSERT INTO user_limits(user_id, daily_limit) VALUES(?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET daily_limit=excluded.daily_limit",
            (user_id, daily_limit),
        )
        connection.commit()


def reset_limit(user_id: int) -> None:
    with _connect() as connection:
        connection.execute("DELETE FROM user_limits WHERE user_id = ?", (user_id,))
        connection.commit()


def try_consume(user_id: int, video_count: int) -> bool:
    """Atomically consume quota after a successful resolver result.

    A negative configured limit means unlimited. Zero blocks the user.
    Failed/verification/API errors should never call this function.
    """
    if video_count <= 0:
        return True

    today = _today()
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        limit = _configured_limit(connection, user_id)
        row = connection.execute(
            "SELECT video_count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
        used = int(row["video_count"]) if row else 0

        if limit >= 0 and used + video_count > limit:
            connection.rollback()
            return False

        connection.execute(
            "INSERT INTO daily_usage(user_id, usage_date, video_count) VALUES(?, ?, ?) "
            "ON CONFLICT(user_id, usage_date) DO UPDATE SET video_count = video_count + excluded.video_count",
            (user_id, today, video_count),
        )
        connection.commit()
        return True


def get_lifetime_video_count(user_id: int) -> int:
    """Return the total successfully consumed video quota across all dates."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT COALESCE(SUM(video_count), 0) AS total FROM daily_usage WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def is_admin(user_id: int) -> bool:
    raw = os.getenv("ADMIN_USER_IDS", "").strip()
    if not raw:
        return False
    allowed: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            allowed.add(int(item))
        except ValueError:
            continue
    return user_id in allowed


def count_video_files(files) -> int:
    """Count video files only, based on file_type and common video extensions."""
    video_extensions = {
        ".3gp", ".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg",
        ".mpg", ".ts", ".webm", ".wmv", ".m2ts", ".mts", ".vob",
    }
    count = 0
    for item in files or []:
        file_type = str(getattr(item, "file_type", "") or "").lower().strip()
        name = str(getattr(item, "name", "") or "").lower().strip()
        if file_type == "video" or any(name.endswith(ext) for ext in video_extensions):
            count += 1
    return count

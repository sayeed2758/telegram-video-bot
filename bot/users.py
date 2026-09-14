"""Persistent lightweight Telegram user registry for admin broadcasts."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("USERS_DB_PATH", str(DATA_DIR / "users.sqlite3")))
TIMEZONE = ZoneInfo(os.getenv("RATE_LIMIT_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            first_name TEXT NOT NULL DEFAULT '',
            last_seen TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    return connection


def register_user(user) -> None:
    """Add/update a Telegram user who interacts with the bot."""
    if user is None:
        return
    now = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    username = str(user.username or "")[:255]
    first_name = str(user.first_name or user.full_name or "Telegram User")[:255]
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_seen, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_seen=excluded.last_seen,
                is_active=1
            """,
            (int(user.id), username, first_name, now),
        )
        connection.commit()


def get_broadcast_users() -> list[int]:
    """Return active users, including users known to the older Phase 23-27 databases."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT user_id FROM users WHERE is_active = 1 ORDER BY user_id"
        ).fetchall()
    user_ids = {int(row["user_id"]) for row in rows}

    # Backfill recipients from the existing rate-limit/history databases so a
    # fresh Phase 28 registry does not exclude users who already used the bot.
    legacy_paths = (
        DATA_DIR / "rate_limits.sqlite3",
        DATA_DIR / "history.sqlite3",
    )
    for path in legacy_paths:
        if not path.is_file():
            continue
        try:
            with sqlite3.connect(path, timeout=5) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                for table in ("daily_usage", "user_limits", "processing_history"):
                    if table not in tables:
                        continue
                    rows = connection.execute(f"SELECT DISTINCT user_id FROM {table}").fetchall()
                    user_ids.update(int(row[0]) for row in rows if row and row[0] is not None)
        except sqlite3.Error:
            continue

    return sorted(user_ids)


def mark_inactive(user_id: int) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE users SET is_active = 0 WHERE user_id = ?",
            (int(user_id),),
        )
        connection.commit()


def mark_active(user_id: int) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE users SET is_active = 1 WHERE user_id = ?",
            (int(user_id),),
        )
        connection.commit()


def get_user_registry_stats() -> dict[str, int]:
    with _connect() as connection:
        total = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0)
        active = int(
            connection.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0] or 0
        )
    return {"total": total, "active": active}

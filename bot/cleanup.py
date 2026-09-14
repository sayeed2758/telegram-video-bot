"""Phase 39: automatic one-hour cleanup for transient history data."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.subscription import purge_expired_subscriptions

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
HISTORY_DB = Path(os.getenv("HISTORY_DB_PATH", str(DATA_DIR / "history.sqlite3")))
TIMEZONE = ZoneInfo(os.getenv("RATE_LIMIT_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata")
HISTORY_TTL_SECONDS = max(300, int(os.getenv("HISTORY_TTL_SECONDS", "3600").strip() or "3600"))
CLEANUP_INTERVAL_SECONDS = max(300, int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600").strip() or "3600"))


def purge_expired_history() -> int:
    """Delete history entries older than the configured TTL."""
    if not HISTORY_DB.exists():
        return 0

    cutoff = (datetime.now(TIMEZONE) - timedelta(seconds=HISTORY_TTL_SECONDS)).isoformat(timespec="seconds")
    try:
        with sqlite3.connect(HISTORY_DB, timeout=10) as connection:
            connection.execute("PRAGMA busy_timeout=5000")
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "processing_history" not in tables:
                return 0
            cursor = connection.execute(
                "DELETE FROM processing_history WHERE created_at < ?",
                (cutoff,),
            )
            connection.commit()
            return int(cursor.rowcount or 0)
    except sqlite3.Error:
        # Cleanup must never break normal bot operation.
        return 0


async def cleanup_loop(stop_event) -> None:
    """Run cleanup approximately once per hour until asked to stop."""
    import asyncio

    while not stop_event.is_set():
        try:
            purge_expired_history()
        except Exception:
            pass
        try:
            purge_expired_subscriptions()
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=CLEANUP_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            continue

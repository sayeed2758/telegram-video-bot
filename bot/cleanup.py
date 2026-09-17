"""Phase 8: automatic cleanup and lightweight SQLite health maintenance."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.subscription import build_expiry_message, expire_due_subscriptions

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TIMEZONE = ZoneInfo(os.getenv("RATE_LIMIT_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata")
HISTORY_DB = Path(os.getenv("HISTORY_DB_PATH", str(DATA_DIR / "history.sqlite3")))
ANALYTICS_DB = Path(os.getenv("ANALYTICS_DB_PATH", str(DATA_DIR / "analytics.sqlite3")))
RATE_LIMIT_DB = Path(os.getenv("RATE_LIMIT_DB_PATH", str(DATA_DIR / "rate_limits.sqlite3")))
SUBSCRIPTIONS_DB = Path(os.getenv("SUBSCRIPTIONS_DB_PATH", str(DATA_DIR / "subscriptions.sqlite3")))

HISTORY_TTL_SECONDS = max(300, int(os.getenv("HISTORY_TTL_SECONDS", "3600").strip() or "3600"))
ANALYTICS_TTL_DAYS = max(7, int(os.getenv("ANALYTICS_TTL_DAYS", "30").strip() or "30"))
RATE_USAGE_TTL_DAYS = max(30, int(os.getenv("RATE_USAGE_TTL_DAYS", "90").strip() or "90"))
CLEANUP_INTERVAL_SECONDS = max(300, int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600").strip() or "3600"))


def _cutoff(days: int) -> str:
    return (datetime.now(TIMEZONE) - timedelta(days=days)).isoformat(timespec="seconds")


def purge_expired_history() -> int:
    """Delete history entries older than the configured TTL."""
    if not HISTORY_DB.exists():
        return 0
    cutoff = (datetime.now(TIMEZONE) - timedelta(seconds=HISTORY_TTL_SECONDS)).isoformat(timespec="seconds")
    try:
        with sqlite3.connect(HISTORY_DB, timeout=10) as connection:
            connection.execute("PRAGMA busy_timeout=5000")
            tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "processing_history" not in tables:
                return 0
            cursor = connection.execute("DELETE FROM processing_history WHERE created_at < ?", (cutoff,))
            connection.commit()
            return int(cursor.rowcount or 0)
    except sqlite3.Error:
        return 0


def purge_expired_analytics() -> int:
    """Delete analytics events beyond the configured retention window."""
    if not ANALYTICS_DB.exists():
        return 0
    try:
        with sqlite3.connect(ANALYTICS_DB, timeout=10) as connection:
            connection.execute("PRAGMA busy_timeout=5000")
            row = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='analytics_events'"
            ).fetchone()
            if not row or int(row[0]) == 0:
                return 0
            cursor = connection.execute("DELETE FROM analytics_events WHERE created_at < ?", (_cutoff(ANALYTICS_TTL_DAYS),))
            connection.commit()
            return int(cursor.rowcount or 0)
    except sqlite3.Error:
        return 0


def purge_old_usage() -> int:
    """Delete stale daily usage rows while keeping custom per-user limits."""
    if not RATE_LIMIT_DB.exists():
        return 0
    try:
        with sqlite3.connect(RATE_LIMIT_DB, timeout=10) as connection:
            connection.execute("PRAGMA busy_timeout=5000")
            row = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='daily_usage'"
            ).fetchone()
            if not row or int(row[0]) == 0:
                return 0
            cutoff_date = (datetime.now(TIMEZONE).date() - timedelta(days=RATE_USAGE_TTL_DAYS)).isoformat()
            cursor = connection.execute("DELETE FROM daily_usage WHERE usage_date < ?", (cutoff_date,))
            connection.commit()
            return int(cursor.rowcount or 0)
    except sqlite3.Error:
        return 0


def maintain_sqlite_databases() -> dict[str, int]:
    """Checkpoint WAL files and run lightweight SQLite optimizer hints."""
    maintained = 0
    failed = 0
    for db_path in (HISTORY_DB, ANALYTICS_DB, RATE_LIMIT_DB, SUBSCRIPTIONS_DB):
        if not db_path.exists():
            continue
        try:
            with sqlite3.connect(db_path, timeout=10) as connection:
                connection.execute("PRAGMA busy_timeout=5000")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("PRAGMA optimize")
            maintained += 1
        except sqlite3.Error:
            failed += 1
    return {"maintained": maintained, "failed": failed}


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        try:
            counts[str(name)] = int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] or 0)
        except sqlite3.Error:
            counts[str(name)] = -1
    return counts


def database_health() -> list[dict[str, object]]:
    """Return safe health information for the bot's SQLite databases."""
    results: list[dict[str, object]] = []
    databases = [
        ("History", HISTORY_DB),
        ("Analytics", ANALYTICS_DB),
        ("Rate Limits", RATE_LIMIT_DB),
        ("Subscriptions", SUBSCRIPTIONS_DB),
    ]
    for label, path in databases:
        item: dict[str, object] = {
            "name": label,
            "exists": path.exists(),
            "size_bytes": int(path.stat().st_size) if path.exists() else 0,
            "status": "missing",
            "tables": {},
        }
        if not path.exists():
            results.append(item)
            continue
        try:
            with sqlite3.connect(path, timeout=10) as connection:
                connection.execute("PRAGMA busy_timeout=5000")
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0] or "")
                item["status"] = "healthy" if integrity.lower() == "ok" else "check"
                item["integrity"] = integrity[:80]
                item["tables"] = _table_counts(connection)
                wal = Path(str(path) + "-wal")
                shm = Path(str(path) + "-shm")
                item["wal_bytes"] = wal.stat().st_size if wal.exists() else 0
                item["shm_bytes"] = shm.stat().st_size if shm.exists() else 0
        except sqlite3.Error as exc:
            item["status"] = "error"
            item["integrity"] = str(exc)[:80]
        results.append(item)
    return results


def cleanup_all() -> dict[str, object]:
    """Run all safe retention and SQLite maintenance jobs."""
    result = {
        "history_deleted": purge_expired_history(),
        "analytics_deleted": purge_expired_analytics(),
        "usage_deleted": purge_old_usage(),
    }
    result["sqlite"] = maintain_sqlite_databases()
    return result


async def cleanup_loop(stop_event, bot=None) -> None:
    """Run cleanup until asked to stop."""
    import asyncio
    while not stop_event.is_set():
        try:
            cleanup_all()
        except Exception:
            pass
        try:
            expired = expire_due_subscriptions()
            if bot is not None:
                for record in expired:
                    try:
                        await bot.send_message(
                            chat_id=int(record["user_id"]),
                            text=build_expiry_message(record),
                            parse_mode="HTML",
                            reply_markup=None,
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CLEANUP_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue

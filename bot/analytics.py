"""Persistent processing analytics for Phase 29."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("ANALYTICS_DB_PATH", str(DATA_DIR / "analytics.sqlite3")))
TIMEZONE = ZoneInfo(os.getenv("RATE_LIMIT_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            video_count INTEGER NOT NULL DEFAULT 0,
            file_count INTEGER NOT NULL DEFAULT 0,
            error_category TEXT NOT NULL DEFAULT '',
            source_key TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_analytics_created
        ON analytics_events(created_at DESC, id DESC);

        CREATE INDEX IF NOT EXISTS idx_analytics_type_created
        ON analytics_events(event_type, created_at DESC);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_source_key
        ON analytics_events(source_key)
        WHERE source_key <> '';
        """
    )
    return connection



def _now() -> datetime:
    return datetime.now(TIMEZONE).replace(microsecond=0)


def record_event(
    user_id: int | None,
    event_type: str,
    *,
    duration_ms: int = 0,
    video_count: int = 0,
    file_count: int = 0,
    error_category: str = "",
    source_key: str = "",
    created_at: str | None = None,
) -> None:
    """Record one analytics event. Failures here never affect bot processing."""
    try:
        created_at = str(created_at or _now().isoformat(timespec="seconds"))
        with _connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO analytics_events
                    (user_id, event_type, created_at, duration_ms, video_count,
                     file_count, error_category, source_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(user_id) if user_id is not None else None,
                    str(event_type)[:64],
                    created_at,
                    max(0, int(duration_ms)),
                    max(0, int(video_count)),
                    max(0, int(file_count)),
                    str(error_category or "")[:80],
                    str(source_key or "")[:255],
                ),
            )
            connection.commit()
    except (sqlite3.Error, TypeError, ValueError):
        return


def _window_stats(start: datetime, end: datetime | None = None) -> dict[str, Any]:
    end = end or _now()
    start_text = start.isoformat(timespec="seconds")
    end_text = end.isoformat(timespec="seconds")
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS events,
                SUM(CASE WHEN event_type='processing_started' THEN 1 ELSE 0 END) AS requests,
                SUM(CASE WHEN event_type='processing_success' THEN 1 ELSE 0 END) AS successes,
                SUM(CASE WHEN event_type='processing_failure' THEN 1 ELSE 0 END) AS failures,
                SUM(CASE WHEN event_type='quota_blocked' THEN 1 ELSE 0 END) AS quota_blocked,
                SUM(CASE WHEN event_type='processing_success' THEN video_count ELSE 0 END) AS videos,
                COUNT(DISTINCT CASE WHEN event_type IN ('processing_started','processing_success','processing_failure') THEN user_id END) AS active_users,
                AVG(CASE WHEN event_type IN ('processing_success','processing_failure') AND duration_ms > 0 THEN duration_ms END) AS avg_duration_ms
            FROM analytics_events
            WHERE created_at >= ? AND created_at <= ?
            """,
            (start_text, end_text),
        ).fetchone()

        categories = connection.execute(
            """
            SELECT error_category, COUNT(*) AS count
            FROM analytics_events
            WHERE event_type='processing_failure'
              AND created_at >= ? AND created_at <= ?
              AND error_category <> ''
            GROUP BY error_category
            ORDER BY count DESC, error_category ASC
            LIMIT 6
            """,
            (start_text, end_text),
        ).fetchall()

    requests = int(row["requests"] or 0)
    successes = int(row["successes"] or 0)
    failures = int(row["failures"] or 0)
    completed = successes + failures
    success_rate = (successes / completed * 100.0) if completed else 0.0

    return {
        "events": int(row["events"] or 0),
        "requests": requests,
        "successes": successes,
        "failures": failures,
        "quota_blocked": int(row["quota_blocked"] or 0),
        "videos": int(row["videos"] or 0),
        "active_users": int(row["active_users"] or 0),
        "avg_duration_ms": int(row["avg_duration_ms"] or 0),
        "success_rate": success_rate,
        "errors": [{"category": str(r["error_category"]), "count": int(r["count"])} for r in categories],
    }


def get_period_stats(period: str) -> dict[str, Any]:
    now = _now()
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0)
    elif period == "7d":
        start = now - timedelta(days=7)
    elif period == "30d":
        start = now - timedelta(days=30)
    else:
        raise ValueError("Unsupported analytics period")
    stats = _window_stats(start, now)
    stats["period"] = period
    stats["start"] = start
    stats["end"] = now
    return stats


def get_daily_breakdown(days: int = 7) -> list[dict[str, Any]]:
    days = max(1, min(int(days), 31))
    today = _now().date()
    start_date = today - timedelta(days=days - 1)
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=TIMEZONE)
    end = _now()

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT substr(created_at,1,10) AS day,
                SUM(CASE WHEN event_type='processing_started' THEN 1 ELSE 0 END) AS requests,
                SUM(CASE WHEN event_type='processing_success' THEN 1 ELSE 0 END) AS successes,
                SUM(CASE WHEN event_type='processing_failure' THEN 1 ELSE 0 END) AS failures,
                SUM(CASE WHEN event_type='processing_success' THEN video_count ELSE 0 END) AS videos,
                COUNT(DISTINCT CASE WHEN event_type IN ('processing_started','processing_success','processing_failure') THEN user_id END) AS users
            FROM analytics_events
            WHERE created_at >= ? AND created_at <= ?
            GROUP BY substr(created_at,1,10)
            ORDER BY day ASC
            """,
            (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
        ).fetchall()

    by_day = {
        str(r["day"]): {
            "day": str(r["day"]),
            "requests": int(r["requests"] or 0),
            "successes": int(r["successes"] or 0),
            "failures": int(r["failures"] or 0),
            "videos": int(r["videos"] or 0),
            "users": int(r["users"] or 0),
        }
        for r in rows
    }
    return [
        by_day.get(
            (start_date + timedelta(days=index)).isoformat(),
            {
                "day": (start_date + timedelta(days=index)).isoformat(),
                "requests": 0,
                "successes": 0,
                "failures": 0,
                "videos": 0,
                "users": 0,
            },
        )
        for index in range(days)
    ]


def get_top_users(limit: int = 8) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 20))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT user_id,
                   COUNT(CASE WHEN event_type='processing_success' THEN 1 END) AS successful_requests,
                   SUM(CASE WHEN event_type='processing_success' THEN video_count ELSE 0 END) AS videos,
                   COUNT(CASE WHEN event_type='processing_failure' THEN 1 END) AS failures
            FROM analytics_events
            WHERE user_id IS NOT NULL
            GROUP BY user_id
            ORDER BY videos DESC, successful_requests DESC, user_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "user_id": int(r["user_id"]),
            "successful_requests": int(r["successful_requests"] or 0),
            "videos": int(r["videos"] or 0),
            "failures": int(r["failures"] or 0),
        }
        for r in rows
    ]


def get_quality_breakdown(days: int = 30) -> list[dict[str, Any]]:
    """Return quality labels captured from successful resolver results."""
    start = _now() - timedelta(days=max(1, min(int(days), 90)))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT error_category AS quality, COUNT(*) AS count
            FROM analytics_events
            WHERE event_type='resolved_quality'
              AND created_at >= ?
              AND error_category <> ''
            GROUP BY error_category
            ORDER BY count DESC, quality ASC
            LIMIT 8
            """,
            (start.isoformat(timespec="seconds"),),
        ).fetchall()
    return [{"quality": str(r["quality"]), "count": int(r["count"])} for r in rows]


def bootstrap_from_history(history_db_path: Path) -> None:
    """Backfill known successful history once, without duplicating events."""
    if not history_db_path.is_file():
        return
    try:
        with sqlite3.connect(history_db_path, timeout=5) as source:
            source.row_factory = sqlite3.Row
            rows = source.execute(
                "SELECT id, user_id, created_at, file_count, video_count FROM processing_history"
            ).fetchall()
    except sqlite3.Error:
        return

    for row in rows:
        source_key = f"history:{int(row['id'])}"
        record_event(
            int(row["user_id"]),
            "processing_success",
            video_count=int(row["video_count"] or 0),
            file_count=int(row["file_count"] or 0),
            source_key=source_key,
            created_at=str(row["created_at"]),
        )

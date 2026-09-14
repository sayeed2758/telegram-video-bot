"""Persistent protection against upstream PlayTeraBox HTTP 429 responses."""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("API_GUARD_DB_PATH", str(DATA_DIR / "api_guard.sqlite3")))
DEFAULT_COOLDOWN = max(int(os.getenv("TERABOX_API_429_FALLBACK_SECONDS", "120") or "120"), 30)
MAX_COOLDOWN = max(int(os.getenv("TERABOX_API_429_MAX_COOLDOWN_SECONDS", "900") or "900"), DEFAULT_COOLDOWN)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_state (
            provider TEXT PRIMARY KEY,
            blocked_until REAL NOT NULL DEFAULT 0,
            last_status INTEGER,
            last_429_at REAL,
            consecutive_429 INTEGER NOT NULL DEFAULT 0,
            last_retry_after REAL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _ensure_row(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM api_state WHERE provider='playterabox'").fetchone()
    if row:
        return row
    now = time.time()
    conn.execute(
        "INSERT INTO api_state(provider, updated_at) VALUES('playterabox', ?)",
        (now,),
    )
    conn.commit()
    return conn.execute("SELECT * FROM api_state WHERE provider='playterabox'").fetchone()


def _retry_after_seconds(headers, now: float) -> int | None:
    raw = headers.get("Retry-After") if headers else None
    if raw:
        raw = raw.strip()
        try:
            seconds = int(float(raw))
            if seconds >= 0:
                return min(max(seconds, 1), MAX_COOLDOWN)
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            seconds = int(dt.timestamp() - now)
            return min(max(seconds, 1), MAX_COOLDOWN)
        except (TypeError, ValueError, OverflowError):
            pass

    reset_raw = headers.get("X-RateLimit-Reset") if headers else None
    if reset_raw:
        try:
            reset_at = float(reset_raw)
            seconds = int(reset_at - now)
            if seconds > 0:
                return min(max(seconds, 1), MAX_COOLDOWN)
        except ValueError:
            pass
    return None


def get_cooldown() -> dict[str, int | float | bool | None]:
    with _connect() as conn:
        row = _ensure_row(conn)
    remaining = max(int(row["blocked_until"] - time.time()), 0)
    return {
        "blocked": remaining > 0,
        "remaining": remaining,
        "blocked_until": float(row["blocked_until"]),
        "last_status": row["last_status"],
        "last_429_at": row["last_429_at"],
        "consecutive_429": int(row["consecutive_429"]),
        "last_retry_after": row["last_retry_after"],
    }


def record_success(status: int = 200) -> None:
    now = time.time()
    with _connect() as conn:
        _ensure_row(conn)
        conn.execute(
            "UPDATE api_state SET blocked_until=0, last_status=?, consecutive_429=0, last_retry_after=NULL, updated_at=? WHERE provider='playterabox'",
            (status, now),
        )
        conn.commit()


def record_failure(status: int) -> None:
    now = time.time()
    with _connect() as conn:
        _ensure_row(conn)
        conn.execute(
            "UPDATE api_state SET last_status=?, updated_at=? WHERE provider='playterabox'",
            (status, now),
        )
        conn.commit()


def record_rate_limit(headers=None) -> int:
    now = time.time()
    with _connect() as conn:
        row = _ensure_row(conn)
        consecutive = int(row["consecutive_429"]) + 1
        header_seconds = _retry_after_seconds(headers or {}, now)
        if header_seconds is None:
            # Escalate conservatively when the provider does not publish a
            # Retry-After value.  This prevents hammering the same key.
            fallback = DEFAULT_COOLDOWN * (2 ** min(consecutive - 1, 3))
            seconds = min(fallback, MAX_COOLDOWN)
        else:
            seconds = header_seconds
        blocked_until = now + seconds
        conn.execute(
            """
            UPDATE api_state
            SET blocked_until=?, last_status=429, last_429_at=?, consecutive_429=?,
                last_retry_after=?, updated_at=?
            WHERE provider='playterabox'
            """,
            (blocked_until, now, consecutive, seconds, now),
        )
        conn.commit()
    return seconds


def format_status() -> str:
    state = get_cooldown()
    if state["blocked"]:
        remaining = int(state["remaining"])
        mins, secs = divmod(remaining, 60)
        wait = f"{mins}m {secs}s" if mins else f"{secs}s"
        cooldown = f"🔴 Rate limited — local cooldown: <b>{wait}</b>"
    else:
        cooldown = "🟢 API request gate is open"

    last_status = state["last_status"] if state["last_status"] is not None else "—"
    consecutive = int(state["consecutive_429"])
    return (
        "📡 <b>PlayTeraBox API Status</b>\n\n"
        f"{cooldown}\n"
        f"📊 Last HTTP status: <b>{last_status}</b>\n"
        f"🔁 Consecutive 429s: <b>{consecutive}</b>\n"
        f"⏱️ Last cooldown: <b>{int(state['last_retry_after']) if state['last_retry_after'] else 0}s</b>\n\n"
        "The bot will not repeatedly hit the API while the local cooldown is active."
    )

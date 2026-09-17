"""Persistent per-user processing history for successful TeraBox results."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("HISTORY_DB_PATH", str(DATA_DIR / "history.sqlite3")))
TIMEZONE = ZoneInfo(os.getenv("RATE_LIMIT_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata")
DEFAULT_HISTORY_LIMIT = 10
HISTORY_TTL_SECONDS = max(300, int(os.getenv("HISTORY_TTL_SECONDS", "3600").strip() or "3600"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS processing_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            share_url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            video_count INTEGER NOT NULL DEFAULT 0,
            file_names_json TEXT NOT NULL DEFAULT '[]'
        );

        CREATE INDEX IF NOT EXISTS idx_processing_history_user_created
        ON processing_history(user_id, created_at DESC, id DESC);
        """
    )
    cutoff = (datetime.now(TIMEZONE) - timedelta(seconds=HISTORY_TTL_SECONDS)).isoformat(timespec="seconds")
    connection.execute("DELETE FROM processing_history WHERE created_at < ?", (cutoff,))
    connection.commit()
    return connection


def _clean_names(files, max_items: int = 20) -> list[str]:
    names: list[str] = []
    for item in files or []:
        name = str(getattr(item, "name", "") or "Unknown file").strip()
        if not name:
            name = "Unknown file"
        names.append(name[:180])
        if len(names) >= max_items:
            break
    return names



def _canonical_url(value: str) -> str:
    """Canonicalize a public share URL for duplicate detection."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        hostname = (parts.hostname or "").lower()
        if not scheme or not hostname:
            return raw.rstrip("/")
        netloc = hostname
        if parts.port:
            netloc = f"{hostname}:{parts.port}"
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((scheme, netloc, path, parts.query, ""))
    except ValueError:
        return raw.rstrip("/")


def find_recent_duplicate(user_id: int, share_url: str) -> dict | None:
    """Return the user's recent history entry for the same share URL, if any."""
    target = _canonical_url(share_url)
    if not target:
        return None
    rows = get_history(user_id, DEFAULT_HISTORY_LIMIT)
    for item in rows:
        if _canonical_url(item.get("share_url", "")) == target:
            try:
                created = datetime.fromisoformat(str(item["created_at"]))
                age_seconds = max(0, int((datetime.now(TIMEZONE) - created).total_seconds()))
            except (TypeError, ValueError):
                age_seconds = 0
            item = dict(item)
            item["age_seconds"] = age_seconds
            return item
    return None

def record_success(user_id: int, share_url: str, files, video_count: int) -> None:
    """Record one successful processing event.

    A repeated URL for the same user is refreshed to the top of history rather
    than creating duplicate entries. Only successful results should call this.
    """
    if not share_url or video_count <= 0:
        return

    names = _clean_names(files)
    now = datetime.now(TIMEZONE).isoformat(timespec="seconds")
    file_count = len(files or [])

    with _connect() as connection:
        connection.execute(
            "DELETE FROM processing_history WHERE user_id = ? AND share_url = ?",
            (user_id, share_url),
        )
        connection.execute(
            """
            INSERT INTO processing_history
                (user_id, share_url, created_at, file_count, video_count, file_names_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, share_url, now, file_count, int(video_count), json.dumps(names, ensure_ascii=False)),
        )
        connection.execute(
            """
            DELETE FROM processing_history
            WHERE user_id = ?
              AND id NOT IN (
                  SELECT id FROM processing_history
                  WHERE user_id = ?
                  ORDER BY created_at DESC, id DESC
                  LIMIT ?
              )
            """,
            (user_id, user_id, DEFAULT_HISTORY_LIMIT),
        )
        connection.commit()


def get_history(user_id: int, limit: int = DEFAULT_HISTORY_LIMIT) -> list[dict]:
    limit = max(1, min(int(limit), 20))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, share_url, created_at, file_count, video_count, file_names_json
            FROM processing_history
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    history_rows: list[dict] = []
    for row in rows:
        try:
            names = json.loads(row["file_names_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            names = []
        if not isinstance(names, list):
            names = []
        history_rows.append(
            {
                "id": int(row["id"]),
                "share_url": str(row["share_url"]),
                "created_at": str(row["created_at"]),
                "file_count": int(row["file_count"]),
                "video_count": int(row["video_count"]),
                "file_names": [str(name) for name in names[:20]],
            }
        )
    return history_rows


def get_history_item(user_id: int, history_id: int) -> dict | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, share_url, created_at, file_count, video_count, file_names_json
            FROM processing_history
            WHERE user_id = ? AND id = ?
            """,
            (user_id, history_id),
        ).fetchone()

    if row is None:
        return None

    try:
        names = json.loads(row["file_names_json"] or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        names = []
    if not isinstance(names, list):
        names = []

    return {
        "id": int(row["id"]),
        "share_url": str(row["share_url"]),
        "created_at": str(row["created_at"]),
        "file_count": int(row["file_count"]),
        "video_count": int(row["video_count"]),
        "file_names": [str(name) for name in names[:20]],
    }


def clear_history(user_id: int) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM processing_history WHERE user_id = ?",
            (user_id,),
        )
        deleted = cursor.rowcount
        connection.commit()
    return int(deleted)

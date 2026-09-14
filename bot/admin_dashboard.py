from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from bot.history import DB_PATH as HISTORY_DB_PATH
from bot.rate_limiter import (
    DB_PATH as RATE_DB_PATH,
    DEFAULT_LIMIT,
    TIMEZONE,
    get_status,
    reset_limit,
    set_limit,
)
from bot.users import get_user_record, get_user_registry_stats


def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c


def _ensure():
    with _connect(HISTORY_DB_PATH) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS processing_history "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,share_url TEXT NOT NULL,"
            "created_at TEXT NOT NULL,file_count INTEGER NOT NULL DEFAULT 0,video_count INTEGER NOT NULL DEFAULT 0,"
            "file_names_json TEXT NOT NULL DEFAULT '[]')"
        )
    with _connect(RATE_DB_PATH) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS user_limits "
            "(user_id INTEGER PRIMARY KEY,daily_limit INTEGER NOT NULL)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS daily_usage "
            "(user_id INTEGER NOT NULL,usage_date TEXT NOT NULL,video_count INTEGER NOT NULL DEFAULT 0,"
            "PRIMARY KEY(user_id,usage_date))"
        )


def _today():
    return datetime.now(TIMEZONE).date().isoformat()


def get_dashboard_stats():
    _ensure()
    today = _today()
    registry = get_user_registry_stats()
    with _connect(RATE_DB_PATH) as c:
        all_usage_users = int(c.execute("SELECT COUNT(DISTINCT user_id) FROM daily_usage").fetchone()[0] or 0)
        lifetime_videos = int(c.execute("SELECT COALESCE(SUM(video_count),0) FROM daily_usage").fetchone()[0] or 0)
        today_videos = int(
            c.execute("SELECT COALESCE(SUM(video_count),0) FROM daily_usage WHERE usage_date=?", (today,)).fetchone()[0] or 0
        )
        today_active = int(
            c.execute(
                "SELECT COUNT(DISTINCT user_id) FROM daily_usage WHERE usage_date=? AND video_count>0",
                (today,),
            ).fetchone()[0]
            or 0
        )
        custom_limits = int(c.execute("SELECT COUNT(*) FROM user_limits").fetchone()[0] or 0)
    with _connect(HISTORY_DB_PATH) as c:
        history_users = int(c.execute("SELECT COUNT(DISTINCT user_id) FROM processing_history").fetchone()[0] or 0)
        history_entries = int(c.execute("SELECT COUNT(*) FROM processing_history").fetchone()[0] or 0)
        history_videos = int(c.execute("SELECT COALESCE(SUM(video_count),0) FROM processing_history").fetchone()[0] or 0)
    return dict(
        date=today,
        users=max(all_usage_users, history_users, registry["total"]),
        active_registry=registry["active"],
        inactive_registry=registry["inactive"],
        today_active=today_active,
        videos=lifetime_videos,
        today_videos=today_videos,
        custom_limits=custom_limits,
        history_entries=history_entries,
        history_videos=history_videos,
        default_limit=DEFAULT_LIMIT,
    )


def get_users(limit=15):
    _ensure()
    limit = max(1, min(int(limit), 50))
    today = _today()
    users = {}
    with _connect(RATE_DB_PATH) as c:
        rows = c.execute(
            "SELECT user_id,COALESCE(SUM(video_count),0) lifetime_videos,"
            "COALESCE(SUM(CASE WHEN usage_date=? THEN video_count ELSE 0 END),0) today_videos "
            "FROM daily_usage GROUP BY user_id ORDER BY lifetime_videos DESC,user_id LIMIT ?",
            (today, limit),
        ).fetchall()
    for r in rows:
        users[int(r["user_id"])] = {
            "user_id": int(r["user_id"]),
            "lifetime_videos": int(r["lifetime_videos"]),
            "today_videos": int(r["today_videos"]),
        }
    with _connect(HISTORY_DB_PATH) as c:
        rows = c.execute(
            "SELECT user_id,COALESCE(SUM(video_count),0) history_videos "
            "FROM processing_history GROUP BY user_id ORDER BY history_videos DESC LIMIT ?",
            (limit,),
        ).fetchall()
    for r in rows:
        uid = int(r["user_id"])
        users.setdefault(uid, {"user_id": uid, "lifetime_videos": 0, "today_videos": 0})
        users[uid]["history_videos"] = int(r["history_videos"])
    for u in users.values():
        u.setdefault("history_videos", 0)
        st = get_status(u["user_id"])
        u["limit"] = int(st["limit"])
        u["remaining"] = int(st["remaining"])
        identity = get_user_record(u["user_id"]) or {}
        u["username"] = str(identity.get("username") or "")
        u["first_name"] = str(identity.get("first_name") or "")
        u["last_seen"] = str(identity.get("last_seen") or "")
        u["is_active"] = int(identity.get("is_active", 1))
    return sorted(users.values(), key=lambda x: (-x["lifetime_videos"], x["user_id"]))[:limit]


def get_user_admin_info(user_id):
    st = get_status(user_id)
    identity = get_user_record(user_id) or {}
    with _connect(HISTORY_DB_PATH) as c:
        entries = int(
            c.execute("SELECT COUNT(*) FROM processing_history WHERE user_id=?", (user_id,)).fetchone()[0] or 0
        )
        videos = int(
            c.execute("SELECT COALESCE(SUM(video_count),0) FROM processing_history WHERE user_id=?", (user_id,)).fetchone()[0] or 0
        )
        last_video = c.execute(
            "SELECT created_at, file_names_json, video_count FROM processing_history "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return dict(
        user_id=int(user_id),
        username=str(identity.get("username") or ""),
        first_name=str(identity.get("first_name") or ""),
        last_seen=str(identity.get("last_seen") or ""),
        is_active=int(identity.get("is_active", 0 if not identity else 1)),
        date=str(st["date"]),
        limit=int(st["limit"]),
        used=int(st["used"]),
        remaining=int(st["remaining"]),
        history_entries=entries,
        history_videos=videos,
        last_processed_at=str(last_video["created_at"]) if last_video else "",
        last_video_count=int(last_video["video_count"]) if last_video else 0,
    )


def set_user_limit(user_id, limit):
    set_limit(user_id, limit)


def reset_user_limit(user_id):
    reset_limit(user_id)

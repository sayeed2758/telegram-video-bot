import sqlite3
from datetime import datetime, timezone

from .config import DATABASE_PATH


def _connect():
    return sqlite3.connect(DATABASE_PATH)


async def init_db() -> None:
    with _connect() as con:
        con.execute(
            '''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            '''
        )
        con.commit()


async def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute(
            '''
            INSERT INTO users (user_id, username, first_name, joined_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_seen_at = excluded.last_seen_at
            ''',
            (user_id, username, first_name, now, now),
        )
        con.commit()


async def count_users() -> int:
    with _connect() as con:
        row = con.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(row[0])

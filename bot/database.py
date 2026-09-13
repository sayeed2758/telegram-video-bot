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
        con.execute(
            '''
            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        con.execute(
            'CREATE INDEX IF NOT EXISTS idx_request_logs_status ON request_logs(status)'
        )
        con.execute(
            'CREATE INDEX IF NOT EXISTS idx_request_logs_platform ON request_logs(platform)'
        )
        con.execute(
            'CREATE INDEX IF NOT EXISTS idx_request_logs_created ON request_logs(created_at)'
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
        row = con.execute('SELECT COUNT(*) FROM users').fetchone()
        return int(row[0])


async def log_request(user_id: int, platform: str, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute(
            'INSERT INTO request_logs (user_id, platform, status, created_at) VALUES (?, ?, ?, ?)',
            (user_id, platform, status, now),
        )
        con.commit()


async def request_stats() -> dict[str, int]:
    with _connect() as con:
        total = con.execute('SELECT COUNT(*) FROM request_logs').fetchone()[0]
        success = con.execute("SELECT COUNT(*) FROM request_logs WHERE status = 'success'").fetchone()[0]
        failed = con.execute("SELECT COUNT(*) FROM request_logs WHERE status = 'failed'").fetchone()[0]
        terabox = con.execute("SELECT COUNT(*) FROM request_logs WHERE platform = 'terabox'").fetchone()[0]
        diskwala = con.execute("SELECT COUNT(*) FROM request_logs WHERE platform = 'diskwala'").fetchone()[0]
        flezen = con.execute("SELECT COUNT(*) FROM request_logs WHERE platform = 'flezen'").fetchone()[0]

    return {
        'total': int(total),
        'success': int(success),
        'failed': int(failed),
        'terabox': int(terabox),
        'diskwala': int(diskwala),
        'flezen': int(flezen),
    }

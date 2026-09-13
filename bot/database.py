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
        con.execute('CREATE INDEX IF NOT EXISTS idx_request_logs_status ON request_logs(status)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_request_logs_platform ON request_logs(platform)')
        con.execute('CREATE INDEX IF NOT EXISTS idx_request_logs_created ON request_logs(created_at)')
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS user_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                original_url TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        con.execute('CREATE INDEX IF NOT EXISTS idx_user_history_user ON user_history(user_id, id)')
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS rate_limit_state (
                user_id INTEGER PRIMARY KEY,
                day TEXT NOT NULL,
                daily_count INTEGER NOT NULL DEFAULT 0,
                last_request_at TEXT
            )
            """
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


async def recent_requests(limit: int = 10) -> list[dict]:
    limit = max(1, min(int(limit), 25))
    with _connect() as con:
        rows = con.execute(
            "SELECT user_id, platform, status, created_at FROM request_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {'user_id': int(user_id), 'platform': platform, 'status': status, 'created_at': created_at}
        for user_id, platform, status, created_at in rows
    ]


async def recent_users(limit: int = 10) -> list[dict]:
    limit = max(1, min(int(limit), 25))
    with _connect() as con:
        rows = con.execute(
            "SELECT user_id, username, first_name, joined_at, last_seen_at FROM users ORDER BY last_seen_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            'user_id': int(user_id),
            'username': username or '',
            'first_name': first_name or '',
            'joined_at': joined_at,
            'last_seen_at': last_seen_at,
        }
        for user_id, username, first_name, joined_at, last_seen_at in rows
    ]

async def check_and_record_request_limit(
    user_id: int,
    cooldown_seconds: int = 10,
    daily_limit: int = 40,
) -> tuple[bool, int, int]:
    """Atomically enforce a per-user cooldown and UTC daily cap."""
    cooldown_seconds = max(1, int(cooldown_seconds))
    daily_limit = max(1, int(daily_limit))

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    today = now.date().isoformat()

    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")

        row = con.execute(
            'SELECT day, daily_count, last_request_at FROM rate_limit_state WHERE user_id = ?',
            (user_id,),
        ).fetchone()

        if row is None:
            day = today
            daily_count = 0
            last_request_at = None
        else:
            day, daily_count, last_request_at = row
            daily_count = int(daily_count)
            if day != today:
                day = today
                daily_count = 0
                last_request_at = None

        if daily_count >= daily_limit:
            con.execute(
                """
                INSERT INTO rate_limit_state (user_id, day, daily_count, last_request_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    day = excluded.day,
                    daily_count = excluded.daily_count,
                    last_request_at = excluded.last_request_at
                """,
                (user_id, day, daily_count, last_request_at),
            )
            con.commit()
            return False, 0, 0

        if last_request_at:
            try:
                last_dt = datetime.fromisoformat(last_request_at)
                elapsed = (now - last_dt).total_seconds()
                remaining_wait = cooldown_seconds - int(elapsed)
                if remaining_wait > 0:
                    con.rollback()
                    return False, remaining_wait, daily_limit - daily_count
            except ValueError:
                pass

        daily_count += 1

        con.execute(
            """
            INSERT INTO rate_limit_state (user_id, day, daily_count, last_request_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                day = excluded.day,
                daily_count = excluded.daily_count,
                last_request_at = excluded.last_request_at
            """,
            (user_id, day, daily_count, now_iso),
        )
        con.commit()

    return True, 0, daily_limit - daily_count



async def log_history(
    user_id: int,
    platform: str,
    title: str,
    original_url: str,
    status: str = "success",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    safe_title = (title or "TeraBox file").strip()[:500]
    with _connect() as con:
        con.execute(
            """
            INSERT INTO user_history
                (user_id, platform, title, original_url, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, platform, safe_title, original_url, status, now),
        )
        # Keep the latest 30 records per user to avoid unbounded growth.
        con.execute(
            """
            DELETE FROM user_history
            WHERE user_id = ?
              AND id NOT IN (
                  SELECT id FROM user_history
                  WHERE user_id = ?
                  ORDER BY id DESC
                  LIMIT 30
              )
            """,
            (user_id, user_id),
        )
        con.commit()


async def recent_history(user_id: int, limit: int = 10) -> list[dict]:
    limit = max(1, min(int(limit), 15))
    with _connect() as con:
        rows = con.execute(
            """
            SELECT id, platform, title, original_url, status, created_at
            FROM user_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [
        {
            'id': int(row[0]),
            'platform': row[1],
            'title': row[2],
            'original_url': row[3],
            'status': row[4],
            'created_at': row[5],
        }
        for row in rows
    ]

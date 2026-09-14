from __future__ import annotations
import sqlite3
from datetime import datetime
from pathlib import Path
from bot.history import DB_PATH as HISTORY_DB_PATH
from bot.rate_limiter import DB_PATH as RATE_DB_PATH, DEFAULT_LIMIT, TIMEZONE, set_limit, reset_limit, get_status

def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c

def _ensure():
    with _connect(HISTORY_DB_PATH) as c:
        c.execute("CREATE TABLE IF NOT EXISTS processing_history (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,share_url TEXT NOT NULL,created_at TEXT NOT NULL,file_count INTEGER NOT NULL DEFAULT 0,video_count INTEGER NOT NULL DEFAULT 0,file_names_json TEXT NOT NULL DEFAULT '[]')")
    with _connect(RATE_DB_PATH) as c:
        c.execute("CREATE TABLE IF NOT EXISTS user_limits (user_id INTEGER PRIMARY KEY,daily_limit INTEGER NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS daily_usage (user_id INTEGER NOT NULL,usage_date TEXT NOT NULL,video_count INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,usage_date))")

def _today(): return datetime.now(TIMEZONE).date().isoformat()

def get_dashboard_stats():
    _ensure(); today=_today()
    with _connect(RATE_DB_PATH) as c:
        a=int(c.execute("SELECT COUNT(DISTINCT user_id) FROM daily_usage").fetchone()[0] or 0)
        b=int(c.execute("SELECT COALESCE(SUM(video_count),0) FROM daily_usage").fetchone()[0] or 0)
        d=int(c.execute("SELECT COALESCE(SUM(video_count),0) FROM daily_usage WHERE usage_date=?",(today,)).fetchone()[0] or 0)
        e=int(c.execute("SELECT COUNT(DISTINCT user_id) FROM daily_usage WHERE usage_date=? AND video_count>0",(today,)).fetchone()[0] or 0)
        f=int(c.execute("SELECT COUNT(*) FROM user_limits").fetchone()[0] or 0)
    with _connect(HISTORY_DB_PATH) as c:
        g=int(c.execute("SELECT COUNT(DISTINCT user_id) FROM processing_history").fetchone()[0] or 0)
        h=int(c.execute("SELECT COUNT(*) FROM processing_history").fetchone()[0] or 0)
        i=int(c.execute("SELECT COALESCE(SUM(video_count),0) FROM processing_history").fetchone()[0] or 0)
    return dict(date=today,users=max(a,g),videos=b,today_videos=d,today_active=e,custom_limits=f,history_entries=h,history_videos=i,default_limit=DEFAULT_LIMIT)

def get_users(limit=15):
    _ensure(); limit=max(1,min(int(limit),50)); today=_today(); users={}
    with _connect(RATE_DB_PATH) as c:
        rows=c.execute("SELECT user_id,COALESCE(SUM(video_count),0) lifetime_videos,COALESCE(SUM(CASE WHEN usage_date=? THEN video_count ELSE 0 END),0) today_videos FROM daily_usage GROUP BY user_id ORDER BY lifetime_videos DESC,user_id LIMIT ?",(today,limit)).fetchall()
    for r in rows: users[int(r['user_id'])]={'user_id':int(r['user_id']),'lifetime_videos':int(r['lifetime_videos']),'today_videos':int(r['today_videos'])}
    with _connect(HISTORY_DB_PATH) as c:
        rows=c.execute("SELECT user_id,COALESCE(SUM(video_count),0) history_videos FROM processing_history GROUP BY user_id ORDER BY history_videos DESC LIMIT ?",(limit,)).fetchall()
    for r in rows:
        uid=int(r['user_id']); users.setdefault(uid,{'user_id':uid,'lifetime_videos':0,'today_videos':0}); users[uid]['history_videos']=int(r['history_videos'])
    for u in users.values():
        u.setdefault('history_videos',0); st=get_status(u['user_id']); u['limit']=int(st['limit']); u['remaining']=int(st['remaining'])
    return sorted(users.values(),key=lambda x:(-x['lifetime_videos'],x['user_id']))[:limit]

def get_user_admin_info(user_id):
    st=get_status(user_id)
    with _connect(HISTORY_DB_PATH) as c:
        entries=int(c.execute("SELECT COUNT(*) FROM processing_history WHERE user_id=?",(user_id,)).fetchone()[0] or 0)
        videos=int(c.execute("SELECT COALESCE(SUM(video_count),0) FROM processing_history WHERE user_id=?",(user_id,)).fetchone()[0] or 0)
    return dict(user_id=user_id,date=str(st['date']),limit=int(st['limit']),used=int(st['used']),remaining=int(st['remaining']),history_entries=entries,history_videos=videos)

def set_user_limit(user_id,limit): set_limit(user_id,limit)
def reset_user_limit(user_id): reset_limit(user_id)

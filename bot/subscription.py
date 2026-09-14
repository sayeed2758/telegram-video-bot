"""Phase 40 subscription foundation without payment-gateway integration.

Paid plans are purchased by contacting the bot owner. The module tracks 30-day
subscription records and automatically treats expired subscriptions as inactive.
Future phases can activate records after a verified manual payment.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import User

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("SUBSCRIPTIONS_DB_PATH", str(DATA_DIR / "subscriptions.sqlite3")))
TIMEZONE = ZoneInfo(os.getenv("RATE_LIMIT_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata")
CONTACT_USERNAME = os.getenv("SUBSCRIPTION_CONTACT_USERNAME", "Dragonn_Exclusive").strip().lstrip("@")
CONTACT_USER_ID = int(os.getenv("SUBSCRIPTION_CONTACT_USER_ID", "7955228561").strip() or "7955228561")
SUBSCRIPTION_DAYS = max(1, int(os.getenv("SUBSCRIPTION_DAYS", "30").strip() or "30"))

PLANS: dict[str, dict[str, object]] = {
    "pro": {
        "name": "PRO",
        "daily_limit": 50,
        "days": SUBSCRIPTION_DAYS,
        "emoji": "⭐",
        "description": f"50 videos/day • {SUBSCRIPTION_DAYS} days",
    },
    "unlimited": {
        "name": "UNLIMITED",
        "daily_limit": -1,
        "days": SUBSCRIPTION_DAYS,
        "emoji": "💎",
        "description": f"Unlimited videos • {SUBSCRIPTION_DAYS} days",
    },
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            plan_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            daily_limit INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            payment_id TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_expires ON subscriptions(expires_at)"
    )
    return conn


def _now() -> datetime:
    return datetime.now(TIMEZONE).replace(microsecond=0)


def _expire_if_needed(conn: sqlite3.Connection, user_id: int) -> None:
    now = _now().isoformat()
    conn.execute(
        "UPDATE subscriptions SET status='expired', updated_at=? "
        "WHERE user_id=? AND status='active' AND expires_at <= ?",
        (now, int(user_id), now),
    )


def get_subscription(user_id: int) -> dict[str, object] | None:
    with _connect() as conn:
        _expire_if_needed(conn, user_id)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=?",
            (int(user_id),),
        ).fetchone()
    return dict(row) if row else None


def get_active_subscription(user_id: int) -> dict[str, object] | None:
    record = get_subscription(user_id)
    if not record or record.get("status") != "active":
        return None
    return record


def get_effective_limit(user_id: int) -> int | None:
    """Return subscription limit when active; None means use normal rate-limit settings."""
    record = get_active_subscription(user_id)
    if record is None:
        return None
    return int(record["daily_limit"])


def activate_subscription(
    user_id: int,
    plan_id: str,
    source: str = "manual",
    payment_id: str = "",
) -> dict[str, object]:
    """Activate/renew a plan. Intended for a future verified admin/payment flow."""
    plan = PLANS.get(plan_id)
    if plan is None:
        raise ValueError(f"Unknown plan: {plan_id}")

    now = _now()
    expires = now + timedelta(days=int(plan["days"]))
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions
                (user_id, plan_id, status, daily_limit, started_at, expires_at, source, payment_id, updated_at)
            VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                plan_id=excluded.plan_id,
                status='active',
                daily_limit=excluded.daily_limit,
                started_at=excluded.started_at,
                expires_at=excluded.expires_at,
                source=excluded.source,
                payment_id=excluded.payment_id,
                updated_at=excluded.updated_at
            """,
            (
                int(user_id),
                plan_id,
                int(plan["daily_limit"]),
                now.isoformat(),
                expires.isoformat(),
                source[:40],
                payment_id[:255],
                now.isoformat(),
            ),
        )
        conn.commit()
    return get_subscription(user_id) or {}


def expire_subscription(user_id: int) -> bool:
    now = _now().isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE subscriptions SET status='expired', updated_at=? WHERE user_id=? AND status='active'",
            (now, int(user_id)),
        )
        conn.commit()
    return cursor.rowcount > 0


def purge_expired_subscriptions() -> int:
    """Mark every past-due active record as expired."""
    now = _now().isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE subscriptions SET status='expired', updated_at=? WHERE status='active' AND expires_at <= ?",
            (now, now),
        )
        conn.commit()
    return int(cursor.rowcount or 0)


def build_purchase_url(user: User | None, plan_id: str) -> str:
    plan = PLANS[plan_id]
    name = str(plan["name"])
    user_id = str(user.id) if user else "unknown"
    username = f"@{user.username}" if user and user.username else "not set"
    text = (
        f"Hello Shahid Sir, I want to purchase the {name} plan. "
        f"Plan: {name} ({plan['description']}). "
        f"My Telegram User ID: {user_id}. Username: {username}. "
        f"Contact ID: {CONTACT_USER_ID}."
    )
    return f"https://t.me/{CONTACT_USERNAME}?text={quote(text)}"


def build_subscription_text(user: User | None) -> str:
    user_id = int(user.id) if user else 0
    active = get_active_subscription(user_id) if user_id else None
    if active:
        plan = PLANS.get(str(active["plan_id"]), {})
        limit = int(active["daily_limit"])
        limit_text = "♾️ Unlimited" if limit < 0 else f"{limit} videos/day"
        started = str(active["started_at"]).replace("T", " ")
        expires = str(active["expires_at"]).replace("T", " ")
        return (
            "💳 <b>My Subscription</b>\n\n"
            f"{plan.get('emoji', '💳')} <b>Plan:</b> {escape(str(plan.get('name', active['plan_id'])))}\n"
            "🟢 <b>Status:</b> Active\n"
            f"🎯 <b>Limit:</b> {escape(limit_text)}\n"
            f"📅 <b>Started:</b> {escape(started)}\n"
            f"⏳ <b>Expires:</b> {escape(expires)}\n\n"
            "💡 Your subscription will automatically expire after the validity period."
        )

    return (
        "💳 <b>Premium Subscription</b>\n\n"
        "Choose a plan below and contact <b>Shahid Sir</b> to purchase it.\n"
        "Payment integration is not connected yet; your purchase request will be sent directly to the owner.\n\n"
        f"⭐ <b>PRO</b> — 50 videos/day • {SUBSCRIPTION_DAYS} days\n"
        f"💎 <b>UNLIMITED</b> — Unlimited videos • {SUBSCRIPTION_DAYS} days\n"
    )

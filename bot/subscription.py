"""Phase 41 manual subscription management without payment-gateway integration.

Paid plans are purchased by contacting the bot owner. Admins manually activate
verified purchases from Telegram; the bot calculates the exact 30-day validity,
confirms activation to the user, and marks overdue subscriptions expired.
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
    """Activate or renew a subscription for a verified manual purchase.

    A new activation starts immediately. When the same plan is already active,
    the new 30-day period is added to the existing expiry so unused paid time is
    not silently lost. Changing plan starts a fresh period from the activation
    moment.
    """
    plan = PLANS.get(plan_id)
    if plan is None:
        raise ValueError(f"Unknown plan: {plan_id}")

    now = _now()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=? AND status='active'",
            (int(user_id),),
        ).fetchone()

        if existing and str(existing["plan_id"]) == plan_id:
            try:
                current_expiry = datetime.fromisoformat(str(existing["expires_at"]))
                if current_expiry > now:
                    started_at = str(existing["started_at"])
                    expires = current_expiry + timedelta(days=int(plan["days"]))
                else:
                    started_at = now.isoformat()
                    expires = now + timedelta(days=int(plan["days"]))
            except ValueError:
                started_at = now.isoformat()
                expires = now + timedelta(days=int(plan["days"]))
        else:
            started_at = now.isoformat()
            expires = now + timedelta(days=int(plan["days"]))

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
                started_at,
                expires.isoformat(),
                source[:40],
                payment_id[:255],
                now.isoformat(),
            ),
        )
        conn.commit()
    return get_subscription(user_id) or {}


def build_activation_message(record: dict[str, object], renewed: bool = False) -> str:
    """Create the user-facing purchase activation/renewal confirmation."""
    plan_id = str(record.get("plan_id") or "pro")
    plan = PLANS.get(plan_id, {})
    limit = int(record.get("daily_limit", 0))
    limit_text = "♾️ Unlimited" if limit < 0 else f"{limit} videos/day"
    started = str(record.get("started_at") or "").replace("T", " ")
    expires = str(record.get("expires_at") or "").replace("T", " ")
    title = "Subscription Renewed" if renewed else "Subscription Activated"
    verb = "renewed" if renewed else "successfully activated"
    return (
        f"🎉 <b>Thanks for purchasing {escape(str(plan.get('name', plan_id)))}!</b>\n\n"
        f"✅ Your subscription has been <b>{verb}</b>.\n\n"
        f"{plan.get('emoji', '💳')} <b>Plan:</b> {escape(str(plan.get('name', plan_id)))}\n"
        f"🎯 <b>Daily Limit:</b> {escape(limit_text)}\n"
        f"📅 <b>Valid From:</b> {escape(started)} (India time)\n"
        f"⏳ <b>Valid Until:</b> {escape(expires)} (India time)\n"
        "🟢 <b>Status:</b> ACTIVE\n\n"
        "💙 Thank you for supporting Advance Tera Video Bot!\n"
        "🚀 Enjoy your premium access."
    )


def build_expiry_message(record: dict[str, object]) -> str:
    plan_id = str(record.get("plan_id") or "pro")
    plan = PLANS.get(plan_id, {})
    expired_at = str(record.get("expires_at") or "").replace("T", " ")
    return (
        "⏰ <b>Subscription Expired</b>\n\n"
        f"{plan.get('emoji', '💳')} <b>Plan:</b> {escape(str(plan.get('name', plan_id)))}\n"
        f"📅 <b>Expired:</b> {escape(expired_at)} (India time)\n\n"
        "You are now back on the 🆓 <b>FREE</b> plan with the normal daily limit.\n\n"
        "💳 Open <b>/subscription</b> to purchase again."
    )

def expire_subscription(user_id: int) -> bool:
    now = _now().isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE subscriptions SET status='expired', updated_at=? WHERE user_id=? AND status='active'",
            (now, int(user_id)),
        )
        conn.commit()
    return cursor.rowcount > 0


def expire_due_subscriptions() -> list[dict[str, object]]:
    """Mark overdue subscriptions expired and return the records just expired."""
    now = _now().isoformat()
    expired: list[dict[str, object]] = []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM subscriptions WHERE status='active' AND expires_at <= ?",
            (now,),
        ).fetchall()
        for row in rows:
            record = dict(row)
            conn.execute(
                "UPDATE subscriptions SET status='expired', updated_at=? WHERE user_id=? AND status='active'",
                (now, int(record["user_id"])),
            )
            expired.append(record)
        conn.commit()
    return expired


def purge_expired_subscriptions() -> int:
    """Compatibility helper: expire overdue records and return the count."""
    return len(expire_due_subscriptions())


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

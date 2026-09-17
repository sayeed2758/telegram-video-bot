"""Phase 7: lightweight admin alerting with cooldowns.

Alerts are best-effort and never interrupt normal bot processing.
The existing private archive channel is reused by default so no new setup is
required when ARCHIVE_CHANNEL_ID is already configured.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from html import escape
from typing import Deque

from telegram import Bot
from telegram.error import TelegramError

from bot.config import ARCHIVE_CHANNEL_ID

_WINDOW_SECONDS = 10 * 60
_FAILURE_THRESHOLD = 3
_USER_ACTIVITY_THRESHOLD = 8
_ALERT_COOLDOWN = 15 * 60

_failure_times: Deque[float] = deque()
_user_request_times: dict[int, Deque[float]] = defaultdict(deque)
_last_alert: dict[str, float] = {}
_lock = asyncio.Lock()


def _alert_chat_id() -> int | None:
    raw = os.getenv("ADMIN_ALERT_CHANNEL_ID", "").strip() or str(ARCHIVE_CHANNEL_ID or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _trim(queue: Deque[float], now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    while queue and queue[0] < cutoff:
        queue.popleft()


def _can_alert(key: str, now: float) -> bool:
    previous = _last_alert.get(key, 0.0)
    if now - previous < _ALERT_COOLDOWN:
        return False
    _last_alert[key] = now
    return True


async def _send(bot: Bot, text: str) -> None:
    chat_id = _alert_chat_id()
    if chat_id is None:
        return
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_notification=True,
        )
    except TelegramError:
        return
    except Exception:
        return


async def track_request(bot: Bot, user_id: int | None, *, name: str = "Unknown", username: str = "") -> None:
    """Track short-window activity and warn admin on unusually high activity."""
    if user_id is None:
        return
    now = time.monotonic()
    async with _lock:
        q = _user_request_times[int(user_id)]
        q.append(now)
        _trim(q, now)
        count = len(q)
        if count < _USER_ACTIVITY_THRESHOLD or not _can_alert(f"activity:{int(user_id)}", now):
            return

    identity = f"@{escape(username.lstrip('@'))}" if username else escape(name or "Unknown")
    text = (
        "⚠️ <b>High User Activity Alert</b>\n\n"
        f"👤 User: <b>{identity}</b>\n"
        f"🆔 ID: <code>{int(user_id)}</code>\n"
        f"🔗 Requests in last 10 min: <b>{count}</b>\n\n"
        "ℹ️ This is an automated activity warning."
    )
    await _send(bot, text)


async def track_failure(
    bot: Bot,
    user_id: int | None,
    *,
    name: str = "Unknown",
    username: str = "",
    category: str = "Resolver failure",
) -> None:
    """Warn after repeated resolver failures without spamming the channel."""
    now = time.monotonic()
    async with _lock:
        _failure_times.append(now)
        _trim(_failure_times, now)
        count = len(_failure_times)
        if count < _FAILURE_THRESHOLD or not _can_alert("resolver-failure", now):
            return

    identity = f"@{escape(username.lstrip('@'))}" if username else escape(name or "Unknown")
    text = (
        "🚨 <b>Resolver Health Alert</b>\n\n"
        f"❌ Failures in last 10 min: <b>{count}</b>\n"
        f"🧩 Latest category: <b>{escape(category)}</b>\n"
        f"👤 Latest user: <b>{identity}</b>\n"
        f"🆔 ID: <code>{int(user_id) if user_id is not None else '—'}</code>\n\n"
        "⚠️ Repeated resolver failures detected."
    )
    await _send(bot, text)

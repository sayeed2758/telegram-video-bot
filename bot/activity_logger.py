"""Phase 4: private admin activity-channel notifications."""
from __future__ import annotations

import logging
from datetime import datetime
from html import escape
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from telegram import Bot
from telegram.error import TelegramError

from bot.config import ADMIN_ACTIVITY_CHANNEL_ID, RATE_LIMIT_TIMEZONE

logger = logging.getLogger(__name__)
TIMEZONE = ZoneInfo(RATE_LIMIT_TIMEZONE)


def get_activity_channel_id() -> int | None:
    value = str(ADMIN_ACTIVITY_CHANNEL_ID or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _time_now() -> str:
    return datetime.now(TIMEZONE).strftime("%d %b %Y • %I:%M:%S %p")


def _identity(user: Any) -> tuple[str, str, str]:
    user_id = str(getattr(user, "id", ""))
    username = str(getattr(user, "username", "") or "")
    name = str(getattr(user, "full_name", "") or getattr(user, "first_name", "") or "Telegram User")
    username_text = f"@{username}" if username else "No username"
    return name, username_text, user_id


def _platform_from_url(url: str) -> str:
    try:
        host = urlparse(str(url)).netloc.lower().split(":", 1)[0]
    except Exception:
        host = ""
    return host or "Unknown"


async def _send(bot: Bot, text: str) -> bool:
    channel_id = get_activity_channel_id()
    if channel_id is None:
        logger.info("Admin activity channel is not configured; skipping notification.")
        return False
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            disable_notification=True,
        )
        return True
    except TelegramError as exc:
        logger.warning("Admin activity notification failed: %s", exc)
        return False
    except Exception as exc:
        logger.warning("Admin activity notification failed unexpectedly: %s", exc)
        return False


async def notify_new_user(bot: Bot, user: Any) -> bool:
    name, username, user_id = _identity(user)
    text = (
        "🆕 <b>NEW USER</b>\n\n"
        f"👤 <b>Name:</b> {escape(name)}\n"
        f"🔗 <b>Username:</b> {escape(username)}\n"
        f"🆔 <b>User ID:</b> <code>{escape(user_id)}</code>\n"
        f"🕐 <b>Joined:</b> {escape(_time_now())}"
    )
    return await _send(bot, text)


async def notify_processing(
    bot: Bot,
    user: Any,
    source_url: str,
    files: list[Any],
    *,
    cache_hit: bool,
    duration_ms: int,
    success: bool,
    error: str = "",
) -> bool:
    name, username, user_id = _identity(user)
    status_line = "✅ <b>SUCCESS</b>" if success else "❌ <b>FAILED</b>"
    lines = [
        "🎬 <b>VIDEO PROCESSING</b>",
        "",
        f"{status_line}",
        f"👤 <b>User:</b> {escape(name)}",
        f"🔗 <b>Username:</b> {escape(username)}",
        f"🆔 <b>User ID:</b> <code>{escape(user_id)}</code>",
        f"🌐 <b>Platform:</b> {escape(_platform_from_url(source_url))}",
        f"🔗 <b>Source:</b> <code>{escape(source_url)}</code>",
        f"⚡ <b>Cache:</b> {'HIT' if cache_hit else 'MISS'}",
        f"⏱️ <b>Processing:</b> {duration_ms} ms",
        f"🕐 <b>Time:</b> {escape(_time_now())}",
    ]
    if success:
        lines.append(f"📦 <b>Files:</b> {len(files)}")
        for index, item in enumerate(files, start=1):
            item_name = str(getattr(item, "name", "Unknown file") or "Unknown file")
            size = str(getattr(item, "size", "Unknown") or "Unknown")
            file_type = str(getattr(item, "file_type", "video") or "video")
            duration = str(getattr(item, "duration", "") or "")
            quality = str(getattr(item, "quality", "") or "")
            direct = bool(getattr(item, "direct_url", None))
            stream = bool(getattr(item, "stream_url", None) or getattr(item, "quality_urls", None))
            lines.extend([
                "",
                f"<b>{index}. {escape(item_name)}</b>",
                f"💾 Size: {escape(size)}",
                f"📁 Type: {escape(file_type)}",
                f"⏱ Duration: {escape(duration) if duration else '—'}",
                f"📺 Quality: {escape(quality) if quality else '—'}",
                f"▶️ Playback: {'Available' if stream else 'Unavailable'}",
                f"📥 Download URL: {'Available' if direct else 'Unavailable'}",
            ])
    elif error:
        lines.extend(["", f"⚠️ <b>Error:</b> {escape(str(error)[:1000])}"])
    return await _send(bot, "\n".join(lines))


async def inspect_activity_channel(bot: Bot) -> dict[str, Any]:
    channel_id = get_activity_channel_id()
    if channel_id is None:
        return {"ok": False, "configured": False, "reason": "ADMIN_ACTIVITY_CHANNEL_ID is missing or invalid."}
    try:
        chat = await bot.get_chat(chat_id=channel_id)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=channel_id, user_id=me.id)
    except TelegramError as exc:
        return {"ok": False, "configured": True, "channel_id": channel_id, "reason": str(exc)}
    status = str(getattr(member, "status", "unknown"))
    can_post = getattr(member, "can_post_messages", None)
    is_admin = status in {"administrator", "creator"}
    return {
        "ok": bool(is_admin and (can_post is not False)),
        "configured": True,
        "channel_id": channel_id,
        "title": str(getattr(chat, "title", "Untitled channel") or "Untitled channel"),
        "username": str(getattr(chat, "username", "") or ""),
        "status": status,
        "can_post": can_post,
        "is_admin": is_admin,
    }

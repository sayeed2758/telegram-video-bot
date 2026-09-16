"""Phase 1 private Telegram archive-channel connection helpers."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import Bot
from telegram.error import TelegramError

from bot.config import ARCHIVE_CHANNEL_ID

logger = logging.getLogger(__name__)


def get_archive_channel_id() -> int | None:
    """Return the configured archive channel id, or None when not configured."""
    value = str(ARCHIVE_CHANNEL_ID or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def inspect_archive_channel(bot: Bot) -> dict[str, Any]:
    """Inspect archive-channel access without sending any message."""
    channel_id = get_archive_channel_id()
    if channel_id is None:
        return {
            "ok": False,
            "configured": False,
            "reason": "ARCHIVE_CHANNEL_ID is missing or invalid.",
        }

    try:
        chat = await bot.get_chat(chat_id=channel_id)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=channel_id, user_id=me.id)
    except TelegramError as exc:
        logger.warning("Archive channel inspection failed: %s", exc)
        return {
            "ok": False,
            "configured": True,
            "reason": str(exc),
            "channel_id": channel_id,
        }

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


async def send_phase1_test(bot: Bot) -> dict[str, Any]:
    """Send a small test message to prove the bot can post to the channel.

    The message is removed a few seconds later on a best-effort basis so Phase 1
    does not leave permanent test content in the archive channel.
    """
    info = await inspect_archive_channel(bot)
    if not info.get("ok"):
        return info

    channel_id = int(info["channel_id"])
    try:
        message = await bot.send_message(
            chat_id=channel_id,
            text=(
                "✅ <b>Phase 1 Archive Channel Test</b>\n\n"
                "The bot can access and post to the configured private channel.\n"
                "This test message will be removed automatically."
            ),
            parse_mode="HTML",
            disable_notification=True,
        )
    except TelegramError as exc:
        logger.warning("Archive channel test send failed: %s", exc)
        return {
            **info,
            "ok": False,
            "reason": f"Post test failed: {exc}",
        }

    async def _delete_later() -> None:
        await asyncio.sleep(8)
        try:
            await bot.delete_message(chat_id=channel_id, message_id=message.message_id)
        except TelegramError:
            # Delete is best-effort for Phase 1. Posting access is the key test.
            pass

    asyncio.create_task(_delete_later())
    return {
        **info,
        "ok": True,
        "test_message_id": int(message.message_id),
    }

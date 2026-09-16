"""Phase 2: Telegram-native video delivery via a private archive channel.

The bot sends the resolved direct media URL to the configured Telegram archive
channel. Telegram stores the uploaded media, so the bot does not keep a
permanent MP4 on the Render filesystem. The same channel message is then copied
into the requesting user's chat. Expiry/deletion tracking is intentionally
left for Phase 3.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from telegram import Bot, Message
from telegram.error import TelegramError

from bot.archive_channel import get_archive_channel_id
from bot.resolver import ResolvedFile

logger = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    ok: bool
    channel_message_id: int | None = None
    user_message_id: int | None = None
    error: str = ""


def _is_video_file(item: ResolvedFile) -> bool:
    file_type = str(item.file_type or "").strip().lower()
    name = str(item.name or "").strip().lower()
    if file_type in {"video", "mp4", "mkv", "mov", "webm", "avi", "m4v", "mpeg", "mpg"}:
        return True
    return name.endswith((".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mpeg", ".mpg"))


def _caption(item: ResolvedFile) -> str:
    name = str(item.name or "Video").strip()
    size = str(item.size or "Unknown").strip()
    duration = str(item.duration or "").strip()
    quality = str(item.quality or "").strip()

    lines = [
        "🎬 <b>Video Ready</b>",
        "",
        f"📁 <b>{_escape_html(name)}</b>",
        f"💾 <b>Size:</b> {_escape_html(size)}",
    ]
    if duration:
        lines.append(f"⏱️ <b>Duration:</b> {_escape_html(duration)}")
    if quality:
        lines.append(f"📺 <b>Quality:</b> {_escape_html(quality)}")
    lines.extend([
        "",
        "☁️ <b>Delivered via Telegram archive.</b>",
        "⏳ Automatic 1-hour expiry will be enabled in the next phase.",
    ])
    return "\n".join(lines)


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


async def deliver_file(
    bot: Bot,
    user_id: int,
    item: ResolvedFile,
) -> DeliveryResult:
    """Upload one resolved video to the archive channel and copy it to the user."""
    archive_id = get_archive_channel_id()
    if archive_id is None:
        return DeliveryResult(False, error="Archive channel is not configured.")

    if not _is_video_file(item):
        return DeliveryResult(False, error="Resolved file is not recognized as a video.")

    direct_url = str(item.direct_url or "").strip()
    if not direct_url:
        return DeliveryResult(False, error="No direct video URL was returned by the resolver.")

    caption = _caption(item)

    try:
        # Passing the direct URL lets Telegram fetch the media directly.
        # No permanent MP4 is written to the Render filesystem.
        channel_message: Message = await bot.send_video(
            chat_id=archive_id,
            video=direct_url,
            caption=caption,
            parse_mode="HTML",
            supports_streaming=True,
            disable_notification=True,
        )
    except TelegramError as exc:
        logger.warning("Archive video upload failed for %s: %s", item.name, exc)
        return DeliveryResult(False, error=f"Archive upload failed: {exc}")

    try:
        copied = await bot.copy_message(
            chat_id=int(user_id),
            from_chat_id=archive_id,
            message_id=channel_message.message_id,
        )
    except TelegramError as exc:
        logger.warning("Archive copy-to-user failed for %s: %s", item.name, exc)
        return DeliveryResult(
            False,
            channel_message_id=int(channel_message.message_id),
            error=f"Video uploaded to archive but could not be copied to user: {exc}",
        )

    return DeliveryResult(
        True,
        channel_message_id=int(channel_message.message_id),
        user_message_id=int(copied.message_id),
    )


async def deliver_files(
    bot: Bot,
    user_id: int,
    files: list[ResolvedFile],
) -> list[DeliveryResult]:
    """Deliver all video files for one resolved share in order."""
    results: list[DeliveryResult] = []
    for item in files:
        result = await deliver_file(bot, user_id, item)
        results.append(result)
    return results

"""Phase 2 alternate delivery: MTProto archive upload + Bot API copy.

The old Bot API URL-upload path fails when Telegram cannot fetch the
PlayTeraBox download URL directly. This implementation uploads through a
private MTProto user session, while the normal bot still performs the final
copy into the user's chat. The source is streamed; no permanent MP4 is stored
on the Render filesystem.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from telegram import Bot
from telegram.error import TelegramError

from bot.archive_channel import get_archive_channel_id
from bot.mtproto_archive import mtproto_configured, upload_url_to_archive
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


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _caption(item: ResolvedFile) -> str:
    lines = [
        "🎬 <b>Video Ready</b>",
        "",
        f"📁 <b>{_escape_html(str(item.name or 'Video'))}</b>",
        f"💾 <b>Size:</b> {_escape_html(str(item.size or 'Unknown'))}",
    ]
    if item.duration:
        lines.append(f"⏱️ <b>Duration:</b> {_escape_html(str(item.duration))}")
    if item.quality:
        lines.append(f"📺 <b>Quality:</b> {_escape_html(str(item.quality))}")
    lines.extend(["", "☁️ <b>Stored in Telegram archive.</b>"])
    return "\n".join(lines)


def _source_url(item: ResolvedFile) -> str | None:
    for value in (item.direct_url, item.stream_url):
        value = str(value or "").strip()
        if value.startswith(("https://", "http://")):
            return value
    if item.quality_urls:
        for quality in ("1080p", "720p", "480p", "360p"):
            value = str(item.quality_urls.get(quality) or "").strip()
            if value.startswith(("https://", "http://")):
                return value
    return None


async def deliver_file(bot: Bot, user_id: int, item: ResolvedFile) -> DeliveryResult:
    archive_id = get_archive_channel_id()
    if archive_id is None:
        return DeliveryResult(False, error="Archive channel is not configured.")

    if not _is_video_file(item):
        return DeliveryResult(False, error="Resolved file is not recognized as a video.")

    source_url = _source_url(item)
    if not source_url:
        return DeliveryResult(False, error="The resolver returned no usable media URL.")

    if not await mtproto_configured():
        return DeliveryResult(
            False,
            error=(
                "Large-file Telegram delivery is not configured yet. "
                "Set the MTProto API ID, API hash and session string in Render."
            ),
        )

    caption = _caption(item)
    upload = await upload_url_to_archive(source_url, caption, str(item.name or "video.mp4"))
    if not upload.ok or not upload.channel_message_id:
        return DeliveryResult(False, error=f"Archive upload failed: {upload.error}")

    try:
        copied = await bot.copy_message(
            chat_id=int(user_id),
            from_chat_id=archive_id,
            message_id=int(upload.channel_message_id),
        )
    except TelegramError as exc:
        logger.warning("Archive copy-to-user failed for %s: %s", item.name, exc)
        return DeliveryResult(
            False,
            channel_message_id=upload.channel_message_id,
            error=f"Video reached archive but could not be copied to user: {exc}",
        )

    return DeliveryResult(
        True,
        channel_message_id=upload.channel_message_id,
        user_message_id=int(copied.message_id),
    )


async def deliver_files(bot: Bot, user_id: int, files: list[ResolvedFile]) -> list[DeliveryResult]:
    results: list[DeliveryResult] = []
    for item in files:
        results.append(await deliver_file(bot, user_id, item))
    return results

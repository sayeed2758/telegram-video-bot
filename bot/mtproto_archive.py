"""Large Telegram archive uploader using a private MTProto user session.

This module is intentionally separate from the Bot API webhook client.
The user-session uploads media to the private archive channel, after which the
existing bot account can copy the channel message into the requesting chat.

The source media is streamed from the resolved HTTP URL into the MTProto
uploader. No permanent MP4 is written to the Render filesystem. A known
Content-Length is preferred because Telegram's MTProto uploader needs the
file size when a stream is supplied.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import httpx
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message as TelethonMessage

from bot.config import (
    ARCHIVE_CHANNEL_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_SESSION_STRING,
)

logger = logging.getLogger(__name__)

_CLIENT: TelegramClient | None = None
_CLIENT_LOCK = asyncio.Lock()

SOURCE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept": "video/*,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class MTProtoUploadResult:
    ok: bool
    channel_message_id: int | None = None
    error: str = ""


class _HTTPAsyncReader:
    """Adapt an httpx async byte iterator to Telethon's async file interface."""

    def __init__(self, iterator: AsyncIterator[bytes]):
        self._iterator = iterator
        self._buffer = bytearray()
        self._done = False

    async def read(self, size: int = -1) -> bytes:
        if self._done:
            data = bytes(self._buffer)
            self._buffer.clear()
            return data

        target = max(1, int(size))
        while len(self._buffer) < target:
            try:
                chunk = await self._iterator.__anext__()
            except StopAsyncIteration:
                self._done = True
                break
            if chunk:
                self._buffer.extend(chunk)

        if size == -1:
            data = bytes(self._buffer)
            self._buffer.clear()
            return data

        data = bytes(self._buffer[:target])
        del self._buffer[:target]
        return data


async def mtproto_configured() -> bool:
    return bool(
        TELEGRAM_API_ID
        and TELEGRAM_API_HASH
        and TELEGRAM_SESSION_STRING
        and str(ARCHIVE_CHANNEL_ID or "").strip()
    )


async def _get_client() -> TelegramClient:
    global _CLIENT
    if not await mtproto_configured():
        raise RuntimeError(
            "MTProto archive uploader is not configured. Set "
            "TELEGRAM_API_ID, TELEGRAM_API_HASH and "
            "TELEGRAM_SESSION_STRING in Render."
        )

    async with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = TelegramClient(
                StringSession(TELEGRAM_SESSION_STRING),
                TELEGRAM_API_ID,
                TELEGRAM_API_HASH,
                auto_reconnect=True,
            )

        if not _CLIENT.is_connected():
            await _CLIENT.connect()

        if not await _CLIENT.is_user_authorized():
            raise RuntimeError(
                "The MTProto session is not authorized. Generate a fresh "
                "session string and update Render."
            )

        return _CLIENT


async def close_mtproto_client() -> None:
    global _CLIENT
    async with _CLIENT_LOCK:
        if _CLIENT is not None:
            try:
                await _CLIENT.disconnect()
            finally:
                _CLIENT = None


async def upload_url_to_archive(
    source_url: str,
    caption: str,
    filename: str,
) -> MTProtoUploadResult:
    """Stream a resolved URL into Telegram and post it to the archive channel."""
    try:
        client = await _get_client()

        channel_id = int(str(ARCHIVE_CHANNEL_ID).strip())
        entity = await client.get_entity(channel_id)

        safe_name = (str(filename or "video.mp4").strip() or "video.mp4")
        if not safe_name.lower().endswith(".mp4"):
            safe_name = f"{safe_name}.mp4"

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=10.0),
            follow_redirects=True,
            headers=SOURCE_HEADERS,
        ) as http:
            response = await http.get(source_url)
            response.raise_for_status()

            content_length = response.headers.get("content-length")
            try:
                file_size = int(content_length) if content_length else 0
            except ValueError:
                file_size = 0

            if file_size <= 0:
                raise RuntimeError(
                    "The source did not provide Content-Length. "
                    "A streaming upload cannot safely determine the file size."
                )

            # Current free Telegram accounts support uploads up to 2 GB; Premium
            # accounts can upload up to 4 GB. Keep a conservative 2 GB safety cap
            # here so the bot never begins a job it cannot complete reliably.
            max_size = 2 * 1024 * 1024 * 1024
            if file_size > max_size:
                raise RuntimeError(
                    "This file is larger than the current 2 GB MTProto safety limit."
                )

            reader = _HTTPAsyncReader(response.aiter_bytes(512 * 1024).__aiter__())
            uploaded = await client.upload_file(
                reader,
                file_size=file_size,
                file_name=safe_name,
                part_size_kb=512,
            )
            uploaded.name = safe_name

            sent: TelethonMessage = await client.send_file(
                entity,
                uploaded,
                caption=caption,
                parse_mode="html",
                supports_streaming=True,
                force_document=False,
            )

        return MTProtoUploadResult(
            ok=True,
            channel_message_id=int(sent.id),
        )

    except Exception as exc:
        logger.warning("MTProto archive upload failed for %s: %s", filename, exc)
        return MTProtoUploadResult(False, error=str(exc))

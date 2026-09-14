"""Phase 31: short-lived result cache and same-URL single-flight protection.

The cache is intentionally in-memory. TeraBox playback/download URLs can expire,
so persisting resolved URLs across Render restarts would be unsafe and stale.
"""
from __future__ import annotations

import asyncio
import copy
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")

DEFAULT_TTL_SECONDS = 120.0
DEFAULT_MAX_ENTRIES = 100


def _positive_float(value: str | None, default: float) -> float:
    try:
        parsed = float(str(value or "").strip())
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(str(value or "").strip())
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


CACHE_TTL_SECONDS = _positive_float(
    os.getenv("RESULT_CACHE_TTL_SECONDS"), DEFAULT_TTL_SECONDS
)
MAX_CACHE_ENTRIES = _positive_int(
    os.getenv("RESULT_CACHE_MAX_ENTRIES"), DEFAULT_MAX_ENTRIES
)


@dataclass
class _CacheEntry(Generic[T]):
    created_at: float
    value: T


_CACHE: dict[str, _CacheEntry[object]] = {}
_INFLIGHT: dict[str, asyncio.Future[object]] = {}
_LOCK = asyncio.Lock()


def cache_key(url: str, password: str | None = None) -> str:
    raw = f"{str(url).strip()}\n{str(password or '').strip()}"
    return sha256(raw.encode("utf-8")).hexdigest()


def _purge_expired(now: float) -> None:
    expired = [
        key
        for key, entry in _CACHE.items()
        if now - entry.created_at >= CACHE_TTL_SECONDS
    ]
    for key in expired:
        _CACHE.pop(key, None)


def _trim_cache() -> None:
    overflow = len(_CACHE) - MAX_CACHE_ENTRIES
    if overflow <= 0:
        return
    oldest = sorted(_CACHE.items(), key=lambda item: item[1].created_at)[:overflow]
    for key, _entry in oldest:
        _CACHE.pop(key, None)


async def get(key: str):
    """Return a fresh cached value or None."""
    now = time.monotonic()
    async with _LOCK:
        _purge_expired(now)
        entry = _CACHE.get(key)
        if entry is None:
            return None
        return copy.deepcopy(entry.value)


async def put(key: str, value) -> None:
    """Store a successful result for the short cache window."""
    now = time.monotonic()
    async with _LOCK:
        _purge_expired(now)
        _CACHE[key] = _CacheEntry(now, copy.deepcopy(value))
        _trim_cache()


async def get_or_resolve(key: str, resolver: Callable[[], Awaitable[T]]) -> tuple[T, bool]:
    """Return (result, cache_hit).

    Concurrent requests for the same URL share one upstream resolver call.
    A successful result is then cached for the short TTL.
    """
    cached = await get(key)
    if cached is not None:
        return cached, True

    leader = False
    async with _LOCK:
        now = time.monotonic()
        _purge_expired(now)
        cached_entry = _CACHE.get(key)
        if cached_entry is not None:
            return copy.deepcopy(cached_entry.value), True

        future = _INFLIGHT.get(key)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            _INFLIGHT[key] = future
            leader = True

    if not leader:
        result = await asyncio.shield(future)
        return copy.deepcopy(result), True

    try:
        result = await resolver()
        if getattr(result, "ok", False):
            await put(key, result)
        future.set_result(copy.deepcopy(result))
        return result, False
    except Exception as exc:
        if not future.done():
            future.set_exception(exc)
        raise
    finally:
        async with _LOCK:
            _INFLIGHT.pop(key, None)

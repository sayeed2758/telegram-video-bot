"""Phase 30: bounded FIFO resolver queue with per-user protection."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Deque


DEFAULT_MAX_CONCURRENT = 2
DEFAULT_MAX_QUEUE_SIZE = 20

from bot.config import MAX_CONCURRENT_RESOLVES, MAX_RESOLVE_QUEUE_SIZE

MAX_CONCURRENT = MAX_CONCURRENT_RESOLVES
MAX_QUEUE_SIZE = MAX_RESOLVE_QUEUE_SIZE


@dataclass
class QueueTicket:
    """One resolver request waiting for permission to run."""

    ticket_id: int
    user_id: int | None
    event: asyncio.Event
    position: int = 0
    queued: bool = False
    granted: bool = False
    released: bool = False
    rejected: bool = False

    async def wait(self) -> None:
        await self.event.wait()


class ResolveQueue:
    """FIFO queue that allows only a bounded number of resolver calls at once."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT, max_queue_size: int = MAX_QUEUE_SIZE) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self.max_queue_size = max(1, int(max_queue_size))
        self._lock = asyncio.Lock()
        self._waiters: Deque[QueueTicket] = deque()
        self._active_users: set[int] = set()
        self._waiting_users: set[int] = set()
        self._active = 0
        self._next_ticket_id = 1

    async def acquire(self, user_id: int | None = None) -> tuple[QueueTicket | None, str | None]:
        """Queue a request and return a ticket, or a reason when rejected."""
        async with self._lock:
            normalized_user = int(user_id) if user_id is not None else None

            if normalized_user is not None:
                if normalized_user in self._active_users:
                    return None, "active"
                if normalized_user in self._waiting_users:
                    return None, "queued"

            if len(self._waiters) >= self.max_queue_size and self._active >= self.max_concurrent:
                return None, "full"

            ticket = QueueTicket(
                ticket_id=self._next_ticket_id,
                user_id=normalized_user,
                event=asyncio.Event(),
            )
            self._next_ticket_id += 1
            self._waiters.append(ticket)
            if normalized_user is not None:
                self._waiting_users.add(normalized_user)

            self._promote_locked()
            if ticket.granted:
                ticket.position = 0
            else:
                ticket.queued = True
                ticket.position = len(self._waiters)

            return ticket, None

    def _promote_locked(self) -> None:
        while self._active < self.max_concurrent and self._waiters:
            ticket = self._waiters.popleft()
            if ticket.user_id is not None:
                self._waiting_users.discard(ticket.user_id)
                self._active_users.add(ticket.user_id)
            self._active += 1
            ticket.granted = True
            ticket.event.set()

            # Refresh the displayed queue position for requests still waiting.
            for index, waiting in enumerate(self._waiters, start=1):
                waiting.position = index

    async def release(self, ticket: QueueTicket | None) -> None:
        if ticket is None or ticket.released:
            return
        async with self._lock:
            if ticket.released:
                return
            ticket.released = True
            if ticket.granted:
                self._active = max(0, self._active - 1)
                if ticket.user_id is not None:
                    self._active_users.discard(ticket.user_id)
                self._promote_locked()

    def snapshot_now(self) -> dict[str, int]:
        """Return queue counters for dashboards without waiting on the async lock."""
        return {
            "active": self._active,
            "waiting": len(self._waiters),
            "max_concurrent": self.max_concurrent,
            "max_queue_size": self.max_queue_size,
        }

    async def snapshot(self) -> dict[str, int]:
        async with self._lock:
            return {
                "active": self._active,
                "waiting": len(self._waiters),
                "max_concurrent": self.max_concurrent,
                "max_queue_size": self.max_queue_size,
            }


RESOLVE_QUEUE = ResolveQueue()


def get_queue_snapshot() -> dict[str, int]:
    return RESOLVE_QUEUE.snapshot_now()


async def get_queue_stats() -> dict[str, int]:
    return await RESOLVE_QUEUE.snapshot()

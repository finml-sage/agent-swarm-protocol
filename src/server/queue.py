"""Async message queue for received messages."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.server.models.requests import MessageRequest


@dataclass
class QueuedMessage:
    message: "MessageRequest"
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MessageQueue:
    def __init__(self, max_size: int = 10000) -> None:
        self._max_size = max_size
        self._queue: asyncio.Queue[QueuedMessage] = asyncio.Queue(maxsize=max_size)
        self._lock = asyncio.Lock()
        self._dropped_count = 0

    async def put(self, message: "MessageRequest") -> bool:
        from src.server.models.requests import MessageRequest
        queued = QueuedMessage(message=message)
        try:
            self._queue.put_nowait(queued)
            return True
        except asyncio.QueueFull:
            async with self._lock:
                self._dropped_count += 1
            return False

    async def get(self, timeout: Optional[float] = None) -> Optional[QueuedMessage]:
        try:
            if timeout is not None:
                return await asyncio.wait_for(self._queue.get(), timeout=timeout)
            return await self._queue.get()
        except asyncio.TimeoutError:
            return None

    def size(self) -> int:
        return self._queue.qsize()

    def is_full(self) -> bool:
        return self._queue.full()

    async def dropped_count(self) -> int:
        async with self._lock:
            return self._dropped_count

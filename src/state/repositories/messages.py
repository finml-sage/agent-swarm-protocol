"""Message queue repository.

.. deprecated:: 2.0.0
    Replaced by :mod:`src.state.repositories.inbox` and
    :mod:`src.state.repositories.outbox`.  Kept during migration period;
    will be removed once all consumers switch to inbox/outbox.
"""
import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import Optional
from src.state.models.message import QueuedMessage, MessageStatus

_MAX_RECENT_LIMIT = 100


class MessageRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None: self._conn = conn
    async def enqueue(self, m: QueuedMessage) -> None:
        await self._conn.execute("INSERT INTO message_queue VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (m.message_id, m.swarm_id, m.sender_id, m.message_type, m.content, m.received_at.isoformat(), None, m.status.value, None))
        await self._conn.commit()
    async def claim_next(self, swarm_id: str) -> Optional[QueuedMessage]:
        c = await self._conn.execute("SELECT * FROM message_queue WHERE swarm_id = ? AND status = ? ORDER BY received_at ASC LIMIT 1", (swarm_id, MessageStatus.PENDING.value))
        r = await c.fetchone()
        if not r: return None
        await self._conn.execute("UPDATE message_queue SET status = ? WHERE message_id = ?", (MessageStatus.PROCESSING.value, r["message_id"]))
        await self._conn.commit()
        return self._row_to_message(r)
    async def complete(self, message_id: str) -> bool:
        c = await self._conn.execute("UPDATE message_queue SET status = ?, processed_at = ? WHERE message_id = ?", (MessageStatus.COMPLETED.value, datetime.now(timezone.utc).isoformat(), message_id))
        await self._conn.commit()
        return c.rowcount > 0
    async def fail(self, message_id: str, error: str) -> bool:
        c = await self._conn.execute("UPDATE message_queue SET status = ?, processed_at = ?, error = ? WHERE message_id = ?", (MessageStatus.FAILED.value, datetime.now(timezone.utc).isoformat(), error, message_id))
        await self._conn.commit()
        return c.rowcount > 0
    async def get_by_id(self, message_id: str) -> Optional[QueuedMessage]:
        c = await self._conn.execute("SELECT * FROM message_queue WHERE message_id = ?", (message_id,))
        r = await c.fetchone()
        return self._row_to_message(r) if r else None
    async def get_pending_count(self, swarm_id: str) -> int:
        c = await self._conn.execute("SELECT COUNT(*) FROM message_queue WHERE swarm_id = ? AND status = ?", (swarm_id, MessageStatus.PENDING.value))
        return (await c.fetchone())[0]
    async def count_by_status(self, swarm_id: str) -> dict[str, int]:
        """Count messages grouped by status for a swarm.

        Returns a dict with keys 'pending', 'completed', 'failed', and
        'total'.  Uses SQL COUNT(*) so the result is never capped by
        _MAX_RECENT_LIMIT.
        """
        c = await self._conn.execute(
            "SELECT status, COUNT(*) FROM message_queue WHERE swarm_id = ? GROUP BY status",
            (swarm_id,),
        )
        rows = await c.fetchall()
        counts: dict[str, int] = {"pending": 0, "completed": 0, "failed": 0}
        for row in rows:
            status_val = row[0]
            count_val = row[1]
            if status_val in counts:
                counts[status_val] = count_val
        counts["total"] = sum(counts.values())
        return counts
    async def list_by_status(self, swarm_id: str, status: MessageStatus | None = None, limit: int = 10) -> list[QueuedMessage]:
        """List messages for a swarm, optionally filtered by status.

        Args:
            swarm_id: The swarm to query messages for.
            status: Filter to this status, or None for all statuses.
            limit: Maximum number of messages to return (capped at 100).

        Returns:
            List of QueuedMessage ordered most-recent first.

        Raises:
            ValueError: If limit is not a positive integer.
        """
        if not isinstance(limit, int) or limit < 1:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")
        capped = min(limit, _MAX_RECENT_LIMIT)
        if status is not None:
            c = await self._conn.execute(
                "SELECT * FROM message_queue WHERE swarm_id = ? AND status = ? ORDER BY received_at DESC LIMIT ?",
                (swarm_id, status.value, capped),
            )
        else:
            c = await self._conn.execute(
                "SELECT * FROM message_queue WHERE swarm_id = ? ORDER BY received_at DESC LIMIT ?",
                (swarm_id, capped),
            )
        rows = await c.fetchall()
        return [self._row_to_message(r) for r in rows]
    async def get_recent(self, swarm_id: str, limit: int = 10) -> list[QueuedMessage]:
        """Get recent completed messages for a swarm.

        Returns up to ``limit`` messages ordered by received_at descending.
        Only messages with COMPLETED status are included (already processed).

        Args:
            swarm_id: The swarm to query messages for.
            limit: Maximum number of messages to return (capped at 100).

        Returns:
            List of QueuedMessage ordered most-recent first.

        Raises:
            ValueError: If limit is not a positive integer.
        """
        return await self.list_by_status(swarm_id, MessageStatus.COMPLETED, limit)
    async def purge_old(self, retention_days: int) -> int:
        c = await self._conn.execute("DELETE FROM message_queue WHERE status IN (?, ?) AND processed_at < ?", (MessageStatus.COMPLETED.value, MessageStatus.FAILED.value, (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()))
        await self._conn.commit()
        return c.rowcount
    def _row_to_message(self, r) -> QueuedMessage:
        return QueuedMessage(message_id=r["message_id"], swarm_id=r["swarm_id"], sender_id=r["sender_id"], message_type=r["message_type"], content=r["content"], received_at=datetime.fromisoformat(r["received_at"]), status=MessageStatus(r["status"]), processed_at=datetime.fromisoformat(r["processed_at"]) if r["processed_at"] else None, error=r["error"])

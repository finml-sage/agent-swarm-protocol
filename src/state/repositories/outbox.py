"""Outbox repository for outgoing message storage."""
import aiosqlite
from datetime import datetime
from typing import Optional

from src.state.models.outbox import OutboxMessage, OutboxStatus

_MAX_LIST_LIMIT = 100


class OutboxRepository:
    """Manages outgoing messages in the outbox table.

    Provides insert and status transition operations for sent messages.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def insert(self, msg: OutboxMessage) -> None:
        """Insert a new message into the outbox.

        Args:
            msg: The outbox message to store.
        """
        await self._conn.execute(
            "INSERT INTO outbox (message_id, swarm_id, recipient_id, "
            "message_type, content, sent_at, status, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg.message_id,
                msg.swarm_id,
                msg.recipient_id,
                msg.message_type,
                msg.content,
                msg.sent_at.isoformat(),
                msg.status.value,
                msg.error,
            ),
        )
        await self._conn.commit()

    async def list_by_swarm(
        self,
        swarm_id: str,
        limit: int = 20,
    ) -> list[OutboxMessage]:
        """List outgoing messages for a swarm.

        Args:
            swarm_id: The swarm to query.
            limit: Maximum messages to return (capped at 100).

        Raises:
            ValueError: If limit is not a positive integer.
        """
        if not isinstance(limit, int) or limit < 1:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")
        capped = min(limit, _MAX_LIST_LIMIT)
        cursor = await self._conn.execute(
            "SELECT * FROM outbox WHERE swarm_id = ? "
            "ORDER BY sent_at DESC LIMIT ?",
            (swarm_id, capped),
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(r) for r in rows]

    async def list_all(self, limit: int = 20) -> list[OutboxMessage]:
        """List all outgoing messages across all swarms.

        Args:
            limit: Maximum messages to return (capped at 100).
        """
        capped = min(limit, _MAX_LIST_LIMIT)
        cursor = await self._conn.execute(
            "SELECT * FROM outbox ORDER BY sent_at DESC LIMIT ?",
            (capped,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(r) for r in rows]

    async def count_by_swarm(self, swarm_id: str) -> dict[str, int]:
        """Count outbox messages grouped by status for a swarm.

        Returns:
            Dict with status names as keys and counts as values,
            plus a 'total' key.
        """
        cursor = await self._conn.execute(
            "SELECT status, COUNT(*) FROM outbox "
            "WHERE swarm_id = ? GROUP BY status",
            (swarm_id,),
        )
        rows = await cursor.fetchall()
        counts: dict[str, int] = {s.value: 0 for s in OutboxStatus}
        for row in rows:
            if row[0] in counts:
                counts[row[0]] = row[1]
        counts["total"] = sum(counts.values())
        return counts

    async def mark_delivered(self, message_id: str) -> bool:
        """Mark a message as delivered.

        Returns:
            True if the message was updated.
        """
        cursor = await self._conn.execute(
            "UPDATE outbox SET status = ? WHERE message_id = ? "
            "AND status = ?",
            (OutboxStatus.DELIVERED.value, message_id, OutboxStatus.SENT.value),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def mark_failed(self, message_id: str, error: str) -> bool:
        """Mark a message as failed with an error reason.

        Args:
            message_id: The message to mark.
            error: Description of the failure.

        Returns:
            True if the message was updated.
        """
        cursor = await self._conn.execute(
            "UPDATE outbox SET status = ?, error = ? "
            "WHERE message_id = ? AND status = ?",
            (
                OutboxStatus.FAILED.value,
                error,
                message_id,
                OutboxStatus.SENT.value,
            ),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> OutboxMessage:
        """Convert a database row to an OutboxMessage."""
        return OutboxMessage(
            message_id=row["message_id"],
            swarm_id=row["swarm_id"],
            recipient_id=row["recipient_id"],
            message_type=row["message_type"],
            content=row["content"],
            sent_at=datetime.fromisoformat(row["sent_at"]),
            status=OutboxStatus(row["status"]),
            error=row["error"],
        )

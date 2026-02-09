"""Inbox repository for incoming message storage."""
import aiosqlite
from datetime import datetime, timezone
from typing import Optional

from src.state.models.inbox import InboxMessage, InboxStatus

_MAX_LIST_LIMIT = 100


class InboxRepository:
    """Manages incoming messages in the inbox table."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def insert(self, msg: InboxMessage) -> None:
        """Insert a new message into the inbox."""
        await self._conn.execute(
            "INSERT INTO inbox (message_id, swarm_id, sender_id, "
            "recipient_id, message_type, content, received_at, "
            "read_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg.message_id, msg.swarm_id, msg.sender_id,
                msg.recipient_id, msg.message_type, msg.content,
                msg.received_at.isoformat(),
                msg.read_at.isoformat() if msg.read_at else None,
                msg.status.value,
            ),
        )
        await self._conn.commit()

    async def get_by_id(self, message_id: str) -> Optional[InboxMessage]:
        """Retrieve a message by its ID."""
        cursor = await self._conn.execute(
            "SELECT * FROM inbox WHERE message_id = ?", (message_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_message(row) if row else None

    async def mark_read(self, message_id: str) -> bool:
        """Mark a message as read, setting read_at timestamp."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            "UPDATE inbox SET status = ?, read_at = ? "
            "WHERE message_id = ? AND status = ?",
            (InboxStatus.READ.value, now, message_id, InboxStatus.UNREAD.value),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def mark_archived(self, message_id: str) -> bool:
        """Mark a message as archived (from unread or read only)."""
        cursor = await self._conn.execute(
            "UPDATE inbox SET status = ? WHERE message_id = ? "
            "AND status IN (?, ?)",
            (InboxStatus.ARCHIVED.value, message_id,
             InboxStatus.UNREAD.value, InboxStatus.READ.value),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def mark_deleted(self, message_id: str) -> bool:
        """Mark a message as deleted (soft delete, from any non-deleted)."""
        cursor = await self._conn.execute(
            "UPDATE inbox SET status = ? WHERE message_id = ? AND status != ?",
            (InboxStatus.DELETED.value, message_id, InboxStatus.DELETED.value),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def list_by_status(
        self, swarm_id: str, status: InboxStatus, limit: int = 20,
    ) -> list[InboxMessage]:
        """List messages for a swarm filtered by status."""
        if not isinstance(limit, int) or limit < 1:
            raise ValueError(f"limit must be a positive integer, got {limit!r}")
        capped = min(limit, _MAX_LIST_LIMIT)
        cursor = await self._conn.execute(
            "SELECT * FROM inbox WHERE swarm_id = ? AND status = ? "
            "ORDER BY received_at DESC LIMIT ?",
            (swarm_id, status.value, capped),
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(r) for r in rows]

    async def list_visible(
        self,
        status_filter: str,
        swarm_id: Optional[str] = None,
        sender_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[InboxMessage]:
        """List inbox messages with optional filters, excluding deleted."""
        capped = min(limit, _MAX_LIST_LIMIT)
        conditions: list[str] = []
        params: list[object] = []
        if status_filter == "all":
            visible = [InboxStatus.UNREAD.value, InboxStatus.READ.value,
                       InboxStatus.ARCHIVED.value]
            placeholders = ",".join("?" for _ in visible)
            conditions.append(f"status IN ({placeholders})")
            params.extend(visible)
        else:
            conditions.append("status = ?")
            params.append(status_filter)
        if swarm_id:
            conditions.append("swarm_id = ?")
            params.append(swarm_id)
        if sender_id:
            conditions.append("sender_id = ?")
            params.append(sender_id)
        where = " AND ".join(conditions)
        params.append(capped)
        cursor = await self._conn.execute(
            f"SELECT * FROM inbox WHERE {where} "
            "ORDER BY received_at DESC LIMIT ?", params,
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(r) for r in rows]

    async def list_recent(
        self, swarm_id: str, limit: int = 10,
    ) -> list[InboxMessage]:
        """Get recent non-deleted messages for context loading."""
        capped = min(limit, _MAX_LIST_LIMIT)
        cursor = await self._conn.execute(
            "SELECT * FROM inbox WHERE swarm_id = ? "
            "AND status != ? ORDER BY received_at DESC LIMIT ?",
            (swarm_id, InboxStatus.DELETED.value, capped),
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(r) for r in rows]

    async def count_by_status(
        self, swarm_id: Optional[str] = None,
    ) -> dict[str, int]:
        """Count messages grouped by status, optionally per swarm."""
        if swarm_id:
            cursor = await self._conn.execute(
                "SELECT status, COUNT(*) FROM inbox "
                "WHERE swarm_id = ? GROUP BY status", (swarm_id,),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT status, COUNT(*) FROM inbox GROUP BY status",
            )
        rows = await cursor.fetchall()
        counts: dict[str, int] = {s.value: 0 for s in InboxStatus}
        for row in rows:
            if row[0] in counts:
                counts[row[0]] = row[1]
        counts["total"] = sum(counts.values())
        return counts

    async def batch_update_status(
        self, message_ids: list[str], new_status: InboxStatus,
    ) -> int:
        """Batch update with transition guards and read_at for 'read'.

        Transitions: read (from unread only), archived (from unread/read),
        deleted (from any except deleted).
        """
        if not message_ids:
            return 0
        placeholders = ",".join("?" for _ in message_ids)
        if new_status == InboxStatus.READ:
            now = datetime.now(timezone.utc).isoformat()
            cursor = await self._conn.execute(
                f"UPDATE inbox SET status = ?, read_at = ? "
                f"WHERE message_id IN ({placeholders}) AND status = ?",
                [new_status.value, now, *message_ids, InboxStatus.UNREAD.value],
            )
        elif new_status == InboxStatus.ARCHIVED:
            cursor = await self._conn.execute(
                f"UPDATE inbox SET status = ? "
                f"WHERE message_id IN ({placeholders}) AND status IN (?, ?)",
                [new_status.value, *message_ids,
                 InboxStatus.UNREAD.value, InboxStatus.READ.value],
            )
        elif new_status == InboxStatus.DELETED:
            cursor = await self._conn.execute(
                f"UPDATE inbox SET status = ? "
                f"WHERE message_id IN ({placeholders}) AND status != ?",
                [new_status.value, *message_ids, InboxStatus.DELETED.value],
            )
        else:
            cursor = await self._conn.execute(
                f"UPDATE inbox SET status = ? "
                f"WHERE message_id IN ({placeholders})",
                [new_status.value, *message_ids],
            )
        await self._conn.commit()
        return cursor.rowcount

    async def purge_deleted(self) -> int:
        """Permanently remove all messages marked as deleted."""
        cursor = await self._conn.execute(
            "DELETE FROM inbox WHERE status = ?", (InboxStatus.DELETED.value,),
        )
        await self._conn.commit()
        return cursor.rowcount

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> InboxMessage:
        """Convert a database row to an InboxMessage."""
        return InboxMessage(
            message_id=row["message_id"], swarm_id=row["swarm_id"],
            sender_id=row["sender_id"], recipient_id=row["recipient_id"],
            message_type=row["message_type"], content=row["content"],
            received_at=datetime.fromisoformat(row["received_at"]),
            status=InboxStatus(row["status"]),
            read_at=(datetime.fromisoformat(row["read_at"])
                     if row["read_at"] else None),
        )

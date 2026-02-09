"""Helpers for inbox API endpoints."""
import aiosqlite
from datetime import datetime
from typing import Optional

from src.server.models.inbox import InboxMessageResponse
from src.state.models.inbox import InboxMessage, InboxStatus
from src.state.repositories.inbox import InboxRepository


def msg_to_response(m: InboxMessage) -> InboxMessageResponse:
    """Convert a state InboxMessage to an API response model."""
    return InboxMessageResponse(
        message_id=m.message_id,
        swarm_id=m.swarm_id,
        sender_id=m.sender_id,
        recipient_id=m.recipient_id,
        message_type=m.message_type,
        status=m.status.value,
        received_at=m.received_at.isoformat(),
        read_at=m.read_at.isoformat() if m.read_at else None,
        content_preview=m.content[:200],
    )


async def list_inbox_messages(
    conn: aiosqlite.Connection,
    status_filter: str,
    swarm_id: Optional[str],
    limit: int,
) -> list[InboxMessage]:
    """Query inbox messages with optional swarm_id and status filters.

    When status_filter is 'all', returns unread + read + archived
    (excludes deleted). Otherwise filters to the requested status.
    """
    if status_filter == "all":
        statuses = [InboxStatus.UNREAD.value, InboxStatus.READ.value, InboxStatus.ARCHIVED.value]
        placeholders = ",".join("?" for _ in statuses)
        if swarm_id:
            cursor = await conn.execute(
                f"SELECT * FROM inbox WHERE swarm_id = ? AND status IN ({placeholders}) "
                "ORDER BY received_at DESC LIMIT ?",
                [swarm_id, *statuses, min(limit, 100)],
            )
        else:
            cursor = await conn.execute(
                f"SELECT * FROM inbox WHERE status IN ({placeholders}) "
                "ORDER BY received_at DESC LIMIT ?",
                [*statuses, min(limit, 100)],
            )
    else:
        if swarm_id:
            cursor = await conn.execute(
                "SELECT * FROM inbox WHERE swarm_id = ? AND status = ? "
                "ORDER BY received_at DESC LIMIT ?",
                (swarm_id, status_filter, min(limit, 100)),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM inbox WHERE status = ? "
                "ORDER BY received_at DESC LIMIT ?",
                (status_filter, min(limit, 100)),
            )
    rows = await cursor.fetchall()
    return [InboxRepository._row_to_message(r) for r in rows]

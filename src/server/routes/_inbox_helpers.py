"""Helpers for inbox API endpoints."""
from typing import Optional

from src.server.models.inbox import InboxMessageResponse
from src.state.models.inbox import InboxMessage


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

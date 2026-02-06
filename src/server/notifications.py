"""Swarm lifecycle event notification service.

Generates and persists system messages for membership lifecycle events
(join, leave, kick, mute, unmute). Notifications are fire-and-forget:
they never block the originating operation.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from src.state.database import DatabaseManager
from src.state.models.message import QueuedMessage
from src.state.repositories.messages import MessageRepository

logger = logging.getLogger(__name__)


class LifecycleAction(Enum):
    """Lifecycle event actions as defined in PROTOCOL.md."""

    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    MEMBER_KICKED = "member_kicked"
    MEMBER_MUTED = "member_muted"
    MEMBER_UNMUTED = "member_unmuted"


@dataclass(frozen=True)
class LifecycleEvent:
    """A swarm lifecycle event to be recorded as a system notification."""

    action: LifecycleAction
    swarm_id: str
    agent_id: str
    initiated_by: Optional[str] = None
    reason: Optional[str] = None


def build_notification_message(event: LifecycleEvent) -> QueuedMessage:
    """Build a QueuedMessage from a lifecycle event.

    The message content is a JSON-serialisable string matching the
    protocol's system message format (type=system, action=<lifecycle>).
    """
    import json

    content = json.dumps({
        "type": "system",
        "action": event.action.value,
        "swarm_id": event.swarm_id,
        "agent_id": event.agent_id,
        "initiated_by": event.initiated_by,
        "reason": event.reason,
    })
    return QueuedMessage(
        message_id=str(uuid.uuid4()),
        swarm_id=event.swarm_id,
        sender_id=event.initiated_by or event.agent_id,
        message_type="system",
        content=content,
        received_at=datetime.now(timezone.utc),
    )


async def persist_notification(
    db: DatabaseManager,
    event: LifecycleEvent,
) -> QueuedMessage:
    """Persist a lifecycle notification to the message queue.

    Args:
        db: Active DatabaseManager instance.
        event: The lifecycle event to record.

    Returns:
        The persisted QueuedMessage.

    Raises:
        ValueError: If the event has invalid fields.
    """
    message = build_notification_message(event)
    async with db.connection() as conn:
        repo = MessageRepository(conn)
        await repo.enqueue(message)
    logger.info(
        "Persisted %s notification: agent=%s swarm=%s",
        event.action.value,
        event.agent_id,
        event.swarm_id,
    )
    return message


async def notify_member_joined(
    db: DatabaseManager,
    swarm_id: str,
    agent_id: str,
) -> QueuedMessage:
    """Record a member_joined notification.

    Called after a successful join to broadcast awareness to existing
    members. The notification is persisted but delivery is handled
    separately by the messaging layer.
    """
    event = LifecycleEvent(
        action=LifecycleAction.MEMBER_JOINED,
        swarm_id=swarm_id,
        agent_id=agent_id,
    )
    return await persist_notification(db, event)


async def notify_member_left(
    db: DatabaseManager,
    swarm_id: str,
    agent_id: str,
) -> QueuedMessage:
    """Record a member_left notification."""
    event = LifecycleEvent(
        action=LifecycleAction.MEMBER_LEFT,
        swarm_id=swarm_id,
        agent_id=agent_id,
    )
    return await persist_notification(db, event)


async def notify_member_kicked(
    db: DatabaseManager,
    swarm_id: str,
    agent_id: str,
    initiated_by: str,
    reason: Optional[str] = None,
) -> QueuedMessage:
    """Record a member_kicked notification."""
    event = LifecycleEvent(
        action=LifecycleAction.MEMBER_KICKED,
        swarm_id=swarm_id,
        agent_id=agent_id,
        initiated_by=initiated_by,
        reason=reason,
    )
    return await persist_notification(db, event)


async def notify_member_muted(
    db: DatabaseManager,
    swarm_id: str,
    agent_id: str,
    initiated_by: str,
    reason: Optional[str] = None,
) -> QueuedMessage:
    """Record a member_muted notification."""
    event = LifecycleEvent(
        action=LifecycleAction.MEMBER_MUTED,
        swarm_id=swarm_id,
        agent_id=agent_id,
        initiated_by=initiated_by,
        reason=reason,
    )
    return await persist_notification(db, event)


async def notify_member_unmuted(
    db: DatabaseManager,
    swarm_id: str,
    agent_id: str,
    initiated_by: str,
) -> QueuedMessage:
    """Record a member_unmuted notification."""
    event = LifecycleEvent(
        action=LifecycleAction.MEMBER_UNMUTED,
        swarm_id=swarm_id,
        agent_id=agent_id,
        initiated_by=initiated_by,
    )
    return await persist_notification(db, event)

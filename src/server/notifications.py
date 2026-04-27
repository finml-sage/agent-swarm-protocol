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
from src.state.models.inbox import InboxMessage, InboxStatus
from src.state.repositories.inbox import InboxRepository

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
    """A swarm lifecycle event to be recorded as a system notification.

    For ``MEMBER_JOINED`` events, ``endpoint`` and ``joined_at`` SHOULD be
    populated so receiver-side dispatchers (see ``system_dispatch.py``) can
    write the new agent into ``swarm_members`` with the authoritative
    master-side values rather than envelope fallbacks (#199).
    """

    action: LifecycleAction
    swarm_id: str
    agent_id: str
    initiated_by: Optional[str] = None
    reason: Optional[str] = None
    endpoint: Optional[str] = None
    joined_at: Optional[str] = None


def build_notification_message(event: LifecycleEvent) -> InboxMessage:
    """Build an InboxMessage from a lifecycle event.

    The message content is a JSON-serialisable string matching the
    protocol's system message format (type=system, action=<lifecycle>).
    Optional fields (``initiated_by``, ``reason``, ``endpoint``,
    ``joined_at``) are emitted when set and omitted when ``None`` to keep
    the payload narrow for non-join events.
    """
    import json

    payload: dict = {
        "type": "system",
        "action": event.action.value,
        "swarm_id": event.swarm_id,
        "agent_id": event.agent_id,
        "initiated_by": event.initiated_by,
        "reason": event.reason,
    }
    if event.endpoint is not None:
        payload["endpoint"] = event.endpoint
    if event.joined_at is not None:
        payload["joined_at"] = event.joined_at

    content = json.dumps(payload)
    return InboxMessage(
        message_id=str(uuid.uuid4()),
        swarm_id=event.swarm_id,
        sender_id=event.initiated_by or event.agent_id,
        message_type="system",
        content=content,
        received_at=datetime.now(timezone.utc),
        status=InboxStatus.UNREAD,
    )


async def persist_notification(
    db: DatabaseManager,
    event: LifecycleEvent,
) -> InboxMessage:
    """Persist a lifecycle notification to the inbox.

    Args:
        db: Active DatabaseManager instance.
        event: The lifecycle event to record.

    Returns:
        The persisted InboxMessage.

    Raises:
        ValueError: If the event has invalid fields.
    """
    message = build_notification_message(event)
    async with db.connection() as conn:
        repo = InboxRepository(conn)
        await repo.insert(message)
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
    endpoint: Optional[str] = None,
    joined_at: Optional[str] = None,
) -> InboxMessage:
    """Record a member_joined notification on the local inbox.

    Called after a successful join to record awareness on the master's
    own inbox. Cross-host delivery to existing members is handled
    separately by ``broadcast_member_joined`` in ``broadcast.py``.

    ``endpoint`` and ``joined_at`` are passed into the payload (#199) so
    the same ``LifecycleEvent`` shape can be reused for the cross-host
    broadcast — receivers need both fields to populate ``swarm_members``.
    """
    event = LifecycleEvent(
        action=LifecycleAction.MEMBER_JOINED,
        swarm_id=swarm_id,
        agent_id=agent_id,
        endpoint=endpoint,
        joined_at=joined_at,
    )
    return await persist_notification(db, event)


async def notify_member_left(
    db: DatabaseManager,
    swarm_id: str,
    agent_id: str,
) -> InboxMessage:
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
) -> InboxMessage:
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
) -> InboxMessage:
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
) -> InboxMessage:
    """Record a member_unmuted notification."""
    event = LifecycleEvent(
        action=LifecycleAction.MEMBER_UNMUTED,
        swarm_id=swarm_id,
        agent_id=agent_id,
        initiated_by=initiated_by,
    )
    return await persist_notification(db, event)

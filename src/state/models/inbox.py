"""Inbox message models."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class InboxStatus(Enum):
    """Status of an inbox message."""

    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"
    DELETED = "deleted"


@dataclass(frozen=True)
class InboxMessage:
    """An incoming message stored in the inbox.

    Attributes:
        message_id: Unique identifier for the message.
        swarm_id: The swarm this message belongs to.
        sender_id: The agent that sent the message.
        recipient_id: The intended recipient (optional for broadcast).
        message_type: The type of message (e.g. 'message', 'system').
        content: The message content (full JSON payload).
        received_at: When the message was received.
        status: Current inbox status.
        read_at: When the message was marked as read.
        deleted_at: When the message was soft-deleted.
    """

    message_id: str
    swarm_id: str
    sender_id: str
    message_type: str
    content: str
    received_at: datetime
    status: InboxStatus = InboxStatus.UNREAD
    recipient_id: Optional[str] = None
    read_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Validate required fields."""
        if not self.message_id:
            raise ValueError("message_id cannot be empty")
        if not self.swarm_id:
            raise ValueError("swarm_id cannot be empty")
        if not self.sender_id:
            raise ValueError("sender_id cannot be empty")
        if not self.message_type:
            raise ValueError("message_type cannot be empty")

"""Outbox message models."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class OutboxStatus(Enum):
    """Status of an outbox message."""

    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True)
class OutboxMessage:
    """An outgoing message stored in the outbox.

    Attributes:
        message_id: Unique identifier for the message.
        swarm_id: The swarm this message belongs to.
        recipient_id: The intended recipient.
        message_type: The type of message (e.g. 'message', 'system').
        content: The message content (full JSON payload).
        sent_at: When the message was sent.
        status: Current outbox status.
        error: Error details if delivery failed.
    """

    message_id: str
    swarm_id: str
    recipient_id: str
    message_type: str
    content: str
    sent_at: datetime
    status: OutboxStatus = OutboxStatus.SENT
    error: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate required fields."""
        if not self.message_id:
            raise ValueError("message_id cannot be empty")
        if not self.swarm_id:
            raise ValueError("swarm_id cannot be empty")
        if not self.recipient_id:
            raise ValueError("recipient_id cannot be empty")
        if not self.message_type:
            raise ValueError("message_type cannot be empty")

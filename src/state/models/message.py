"""Message queue models."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class MessageStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass(frozen=True)
class QueuedMessage:
    message_id: str
    swarm_id: str
    sender_id: str
    message_type: str
    content: str
    received_at: datetime
    status: MessageStatus = MessageStatus.PENDING
    processed_at: Optional[datetime] = None
    error: Optional[str] = None
    def __post_init__(self) -> None:
        if not self.message_id: raise ValueError("message_id cannot be empty")
        if not self.swarm_id: raise ValueError("swarm_id cannot be empty")
        if not self.sender_id: raise ValueError("sender_id cannot be empty")
        if not self.message_type: raise ValueError("message_type cannot be empty")
    def with_status(self, status: MessageStatus, processed_at: Optional[datetime] = None, error: Optional[str] = None) -> "QueuedMessage":
        return QueuedMessage(message_id=self.message_id, swarm_id=self.swarm_id, sender_id=self.sender_id, message_type=self.message_type, content=self.content, received_at=self.received_at, status=status, processed_at=processed_at or self.processed_at, error=error)

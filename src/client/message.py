"""Message models for the Agent Swarm Protocol."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from .types import AttachmentType, MessageType, Priority, ReferenceAction, ReferenceType


class MessageSender(BaseModel):
    agent_id: str = Field(..., min_length=1)
    endpoint: str = Field(..., pattern=r"^https://")


class MessageAttachment(BaseModel):
    type: AttachmentType
    mime_type: str
    content: str


class MessageReference(BaseModel):
    type: ReferenceType
    repo: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
    number: int | None = None
    sha: str | None = None
    url: str | None = None
    action: ReferenceAction | None = None


class Message(BaseModel):
    protocol_version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    message_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sender: MessageSender
    recipient: str
    swarm_id: UUID
    type: MessageType = MessageType.MESSAGE
    content: str
    signature: str = ""
    in_reply_to: UUID | None = None
    thread_id: UUID | None = None
    priority: Priority = Priority.NORMAL
    expires_at: datetime | None = None
    attachments: list[MessageAttachment] | None = None
    references: list[MessageReference] | None = None
    metadata: dict[str, str | int | bool | None] | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: str | datetime) -> datetime:
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v

    def to_signing_dict(self) -> dict:
        return {"message_id": self.message_id, "timestamp": self.timestamp, "swarm_id": self.swarm_id,
                "recipient": self.recipient, "type": self.type.value, "content": self.content}

    def to_wire_format(self) -> dict:
        ts = self.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        r: dict = {"protocol_version": self.protocol_version, "message_id": str(self.message_id),
            "timestamp": ts, "sender": {"agent_id": self.sender.agent_id, "endpoint": self.sender.endpoint},
            "recipient": self.recipient, "swarm_id": str(self.swarm_id), "type": self.type.value,
            "content": self.content, "signature": self.signature}
        if self.in_reply_to:
            r["in_reply_to"] = str(self.in_reply_to)
        if self.thread_id:
            r["thread_id"] = str(self.thread_id)
        if self.priority != Priority.NORMAL:
            r["priority"] = self.priority.value
        if self.expires_at:
            r["expires_at"] = self.expires_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        if self.attachments:
            r["attachments"] = [{"type": a.type.value, "mime_type": a.mime_type, "content": a.content} for a in self.attachments]
        if self.references:
            r["references"] = [self._ref_to_dict(x) for x in self.references]
        if self.metadata:
            r["metadata"] = self.metadata
        return r

    def _ref_to_dict(self, ref: MessageReference) -> dict:
        d: dict = {"type": ref.type.value}
        for k in ("repo", "number", "sha", "url"):
            if getattr(ref, k) is not None:
                d[k] = getattr(ref, k)
        if ref.action:
            d["action"] = ref.action.value
        return d

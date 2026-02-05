"""Message builder with fluent API."""

from datetime import datetime
from uuid import UUID

from .message import Message, MessageAttachment, MessageReference, MessageSender
from .types import AttachmentType, MessageType, Priority, ReferenceAction, ReferenceType


class MessageBuilder:
    def __init__(self, sender_id: str, sender_endpoint: str) -> None:
        self._sender = MessageSender(agent_id=sender_id, endpoint=sender_endpoint)
        self._recipient: str = ""
        self._swarm_id: UUID | None = None
        self._type: MessageType = MessageType.MESSAGE
        self._content: str = ""
        self._in_reply_to: UUID | None = None
        self._thread_id: UUID | None = None
        self._priority: Priority = Priority.NORMAL
        self._expires_at: datetime | None = None
        self._attachments: list[MessageAttachment] = []
        self._references: list[MessageReference] = []
        self._metadata: dict[str, str | int | bool | None] = {}

    def to(self, recipient: str) -> "MessageBuilder":
        self._recipient = recipient
        return self

    def in_swarm(self, swarm_id: UUID) -> "MessageBuilder":
        self._swarm_id = swarm_id
        return self

    def with_content(self, content: str) -> "MessageBuilder":
        self._content = content
        return self

    def as_type(self, msg_type: MessageType) -> "MessageBuilder":
        self._type = msg_type
        return self

    def replying_to(self, message_id: UUID) -> "MessageBuilder":
        self._in_reply_to = message_id
        return self

    def in_thread(self, thread_id: UUID) -> "MessageBuilder":
        self._thread_id = thread_id
        return self

    def with_priority(self, priority: Priority) -> "MessageBuilder":
        self._priority = priority
        return self

    def expires(self, at: datetime) -> "MessageBuilder":
        self._expires_at = at
        return self

    def attach(self, atype: AttachmentType, mime: str, content: str) -> "MessageBuilder":
        self._attachments.append(MessageAttachment(type=atype, mime_type=mime, content=content))
        return self

    def reference(self, rtype: ReferenceType, action: ReferenceAction | None = None,
                  repo: str | None = None, number: int | None = None,
                  sha: str | None = None, url: str | None = None) -> "MessageBuilder":
        self._references.append(MessageReference(type=rtype, repo=repo, number=number, sha=sha, url=url, action=action))
        return self

    def with_metadata(self, key: str, value: str | int | bool | None) -> "MessageBuilder":
        self._metadata[key] = value
        return self

    def build(self) -> Message:
        if not self._recipient:
            raise ValueError("Recipient is required")
        if self._swarm_id is None:
            raise ValueError("Swarm ID is required")
        if not self._content:
            raise ValueError("Content is required")
        return Message(sender=self._sender, recipient=self._recipient, swarm_id=self._swarm_id, type=self._type,
            content=self._content, in_reply_to=self._in_reply_to, thread_id=self._thread_id, priority=self._priority,
            expires_at=self._expires_at, attachments=self._attachments or None, references=self._references or None,
            metadata=self._metadata or None)

"""Pydantic response models for the inbox and outbox API endpoints."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class InboxMessageResponse(BaseModel):
    """Single message in an inbox listing."""

    message_id: str
    swarm_id: str
    sender_id: str
    recipient_id: Optional[str] = None
    message_type: str
    status: str
    received_at: str
    read_at: Optional[str] = None
    content_preview: str


class InboxListResponse(BaseModel):
    """Response for GET /api/inbox."""

    count: int
    messages: list[InboxMessageResponse]


class InboxCountResponse(BaseModel):
    """Response for GET /api/inbox/count."""

    unread: int
    read: int
    archived: int
    deleted: int
    total: int


class InboxStatusResponse(BaseModel):
    """Response for status-change actions on a single message."""

    status: str
    message_id: str


class InboxBatchRequest(BaseModel):
    """Request body for POST /api/inbox/batch."""

    message_ids: list[str] = Field(min_length=1, max_length=100)
    action: Literal["read", "archive", "delete"]


class InboxBatchResponse(BaseModel):
    """Response for POST /api/inbox/batch."""

    action: str
    updated: int
    total: int


class OutboxMessageResponse(BaseModel):
    """Single message in an outbox listing."""

    message_id: str
    swarm_id: str
    recipient_id: str
    message_type: str
    status: str
    sent_at: str
    error: Optional[str] = None
    content_preview: str


class OutboxListResponse(BaseModel):
    """Response for GET /api/outbox."""

    count: int
    messages: list[OutboxMessageResponse]


class OutboxCountResponse(BaseModel):
    """Response for GET /api/outbox/count."""

    sent: int
    delivered: int
    failed: int
    total: int

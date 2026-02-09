"""Pydantic response models for the inbox API endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class InboxMessage(BaseModel):
    """Single message in an inbox listing."""

    message_id: str
    swarm_id: str
    sender_id: str
    message_type: str
    status: str
    received_at: str
    content_preview: str


class InboxListResponse(BaseModel):
    """Response for GET /api/messages."""

    count: int
    messages: list[InboxMessage]


class InboxCountResponse(BaseModel):
    """Response for GET /api/messages/count."""

    pending: int
    completed: int
    failed: int
    total: int


class InboxAckResponse(BaseModel):
    """Response for POST /api/messages/{message_id}/ack."""

    status: Literal["acked", "not_found"]
    message_id: str

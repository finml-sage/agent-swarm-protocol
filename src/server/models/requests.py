"""Request models for API endpoints."""
from typing import Annotated, Literal, Optional, Any
from pydantic import BaseModel, Field, field_validator
import re
from src.server.models.common import Sender, JoinSender

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class MessageRequest(BaseModel):
    protocol_version: Annotated[str, Field()]
    message_id: Annotated[str, Field()]
    timestamp: Annotated[str, Field()]
    sender: Sender
    recipient: Annotated[str, Field()]
    swarm_id: Annotated[str, Field()]
    type: Annotated[Literal["message", "system", "notification"], Field()]
    content: Annotated[str, Field()]
    signature: Annotated[str, Field()]
    in_reply_to: Optional[str] = None
    thread_id: Optional[str] = None
    priority: Literal["low", "normal", "high"] = "normal"
    expires_at: Optional[str] = None
    attachments: Optional[list[dict[str, Any]]] = None
    references: Optional[list[dict[str, Any]]] = None
    metadata: Optional[dict[str, Any]] = None

    @field_validator("protocol_version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not VERSION_PATTERN.match(v):
            raise ValueError("Protocol version must be in format X.Y.Z")
        return v

    @field_validator("message_id", "swarm_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        if not UUID_PATTERN.match(v):
            raise ValueError("Must be a valid UUID")
        return v


class JoinRequest(BaseModel):
    type: Annotated[Literal["system"], Field()]
    action: Annotated[Literal["join_request"], Field()]
    invite_token: Annotated[str, Field()]
    sender: JoinSender

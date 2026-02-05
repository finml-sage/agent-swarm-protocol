"""Response models for API endpoints."""
from typing import Annotated, Literal, Optional, Any
from pydantic import BaseModel, Field
from src.server.models.common import Member


class MessageResponse(BaseModel):
    status: Literal["received"] = "received"
    message_id: Annotated[str, Field()]


class MessageQueuedResponse(BaseModel):
    status: Literal["queued"] = "queued"
    message_id: Annotated[str, Field()]


class JoinAcceptedResponse(BaseModel):
    status: Literal["accepted"] = "accepted"
    swarm_id: Annotated[str, Field()]
    swarm_name: Optional[str] = None
    members: Annotated[list[Member], Field()]


class JoinPendingResponse(BaseModel):
    status: Literal["pending"] = "pending"
    swarm_id: Annotated[str, Field()]
    message: Optional[str] = None


class HealthResponse(BaseModel):
    status: Annotated[Literal["healthy", "degraded"], Field()]
    agent_id: Annotated[str, Field()]
    protocol_version: Annotated[str, Field()]
    timestamp: Annotated[str, Field()]
    message: Optional[str] = None


class AgentInfoResponse(BaseModel):
    agent_id: Annotated[str, Field()]
    endpoint: Annotated[str, Field()]
    public_key: Annotated[str, Field()]
    protocol_version: Annotated[str, Field()]
    capabilities: Annotated[list[str], Field()]
    metadata: Optional[dict[str, Any]] = None


class ErrorDetail(BaseModel):
    code: Annotated[
        Literal[
            "INVALID_FORMAT",
            "INVALID_SIGNATURE",
            "NOT_AUTHORIZED",
            "SWARM_NOT_FOUND",
            "INVALID_TOKEN",
            "RATE_LIMITED",
            "INTERNAL_ERROR",
        ],
        Field(),
    ]
    message: Annotated[str, Field()]
    details: Optional[dict[str, Any]] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail

"""Authentication and authorization for inbound swarm messages."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import aiosqlite

from src.client.crypto import public_key_from_base64, verify_signature
from src.client.exceptions import SignatureError
from src.server.models.requests import MessageRequest
from src.state.repositories.membership import MembershipRepository

MessageAuthenticationCode = Literal[
    "INVALID_FORMAT",
    "INVALID_SIGNATURE",
    "NOT_AUTHORIZED",
    "SWARM_NOT_FOUND",
    "INTERNAL_ERROR",
]


@dataclass(frozen=True)
class MessageAuthenticationError(Exception):
    """Fail-closed inbound-message rejection with protocol error metadata."""

    status_code: int
    code: MessageAuthenticationCode
    reason: str


async def authenticate_message(
    conn: aiosqlite.Connection,
    body: MessageRequest,
    *,
    local_agent_id: str,
    sender_header: str | None,
    protocol_header: str | None,
) -> None:
    """Verify transport claims, membership, recipient, and Ed25519 signature."""
    if sender_header != body.sender.agent_id:
        raise _not_authorized("X-Agent-ID does not match the signed sender")
    if protocol_header != body.protocol_version:
        raise _not_authorized(
            "X-Swarm-Protocol does not match the message protocol version"
        )
    if body.recipient not in (local_agent_id, "broadcast"):
        raise _not_authorized("message recipient is not this agent or broadcast")

    swarm = await MembershipRepository(conn).get_swarm(body.swarm_id)
    if swarm is None:
        raise MessageAuthenticationError(
            status_code=404,
            code="SWARM_NOT_FOUND",
            reason="message references an unknown swarm",
        )

    sender = next(
        (member for member in swarm.members if member.agent_id == body.sender.agent_id),
        None,
    )
    if sender is None:
        raise _not_authorized("sender is not a member of the referenced swarm")
    if sender.endpoint.rstrip("/") != body.sender.endpoint.rstrip("/"):
        raise _not_authorized("sender endpoint does not match registered membership")

    try:
        timestamp = datetime.fromisoformat(body.timestamp.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        public_key = public_key_from_base64(sender.public_key)
    except ValueError as exc:
        raise MessageAuthenticationError(
            status_code=400,
            code="INVALID_FORMAT",
            reason=f"message timestamp is invalid: {exc}",
        ) from exc
    except SignatureError as exc:
        raise MessageAuthenticationError(
            status_code=500,
            code="INTERNAL_ERROR",
            reason="registered sender public key is invalid",
        ) from exc

    is_valid = verify_signature(
        public_key,
        body.signature,
        UUID(body.message_id),
        timestamp,
        UUID(body.swarm_id),
        body.recipient,
        body.type,
        body.content,
    )
    if not is_valid:
        raise MessageAuthenticationError(
            status_code=401,
            code="INVALID_SIGNATURE",
            reason="Ed25519 signature verification failed",
        )


def _not_authorized(reason: str) -> MessageAuthenticationError:
    return MessageAuthenticationError(
        status_code=403,
        code="NOT_AUTHORIZED",
        reason=reason,
    )

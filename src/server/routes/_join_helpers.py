"""Helper functions for the join endpoint."""
import base64
import json
from typing import Sequence

from src.state.join import SwarmNotFoundError
from src.state.models.member import SwarmMember
from src.state.token import TokenPayloadError


def extract_swarm_id(invite_token: str) -> str:
    """Extract swarm_id from JWT payload without signature verification.

    The token signature is verified later by validate_and_join. This
    peek is only used to look up the master's public key from the DB.

    Args:
        invite_token: Raw JWT string (header.payload.signature).

    Returns:
        The swarm_id claim value.

    Raises:
        TokenPayloadError: If the token structure or payload is invalid.
    """
    parts = invite_token.split(".")
    if len(parts) != 3:
        raise TokenPayloadError(
            f"Invalid JWT structure: expected 3 parts, got {len(parts)}"
        )
    payload_b64 = parts[1]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (json.JSONDecodeError, UnicodeDecodeError, Exception) as exc:
        raise TokenPayloadError(f"Cannot decode JWT payload: {exc}") from exc
    swarm_id = payload.get("swarm_id")
    if not swarm_id:
        raise TokenPayloadError("JWT payload missing swarm_id claim")
    return swarm_id


def find_master_public_key(
    members: Sequence[SwarmMember], master_id: str,
) -> bytes:
    """Find the master's raw Ed25519 public key bytes from the member list.

    Args:
        members: Sequence of swarm members.
        master_id: The agent_id of the swarm master.

    Returns:
        Raw 32-byte Ed25519 public key.

    Raises:
        SwarmNotFoundError: If the master is not in the member list.
    """
    for member in members:
        if member.agent_id == master_id:
            return base64.b64decode(member.public_key)
    raise SwarmNotFoundError(
        f"Master '{master_id}' not found in swarm member list"
    )

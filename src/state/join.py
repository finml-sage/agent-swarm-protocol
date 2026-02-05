"""Join flow state operations."""
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from src.state.models.member import SwarmMember, SwarmMembership
from src.state.repositories.membership import MembershipRepository
from src.state.token import (
    InviteTokenClaims,
    TokenError,
    verify_invite_token,
)


class JoinError(Exception):
    """Base class for join operation errors."""


class SwarmNotFoundError(JoinError):
    """Raised when the target swarm does not exist."""


class AlreadyMemberError(JoinError):
    """Raised when the agent is already a member of the swarm."""


class ApprovalRequiredError(JoinError):
    """Raised when the swarm requires master approval for new members."""


@dataclass(frozen=True)
class JoinResult:
    """Result of a successful join operation."""

    swarm_id: str
    swarm_name: str
    members: tuple[SwarmMember, ...]


async def validate_and_join(
    conn: aiosqlite.Connection,
    invite_token: str,
    master_public_key: bytes,
    agent_id: str,
    agent_endpoint: str,
    agent_public_key: str,
) -> JoinResult:
    """Validate an invite token and register the agent as a swarm member.

    This is the primary entry point for the join flow. It performs:
    1. Token signature and expiry validation
    2. Swarm existence lookup
    3. Duplicate membership check
    4. Approval-required check
    5. Member registration

    Args:
        conn: Active database connection.
        invite_token: The raw JWT invite token string.
        master_public_key: Ed25519 public key bytes (32 bytes) of the master.
        agent_id: The joining agent's identifier.
        agent_endpoint: The joining agent's HTTPS endpoint.
        agent_public_key: The joining agent's base64-encoded public key.

    Returns:
        JoinResult with the swarm info and updated member list.

    Raises:
        TokenError: If the invite token is invalid, expired, or forged.
        SwarmNotFoundError: If the swarm does not exist.
        AlreadyMemberError: If the agent is already in the swarm.
        ApprovalRequiredError: If the swarm requires approval.
    """
    claims = verify_invite_token(invite_token, master_public_key)
    repo = MembershipRepository(conn)

    swarm = await repo.get_swarm(claims.swarm_id)
    if swarm is None:
        raise SwarmNotFoundError(
            f"Swarm '{claims.swarm_id}' not found"
        )

    if _is_member(swarm, agent_id):
        raise AlreadyMemberError(
            f"Agent '{agent_id}' is already a member of swarm "
            f"'{claims.swarm_id}'"
        )

    if swarm.settings.require_approval:
        raise ApprovalRequiredError(
            f"Swarm '{claims.swarm_id}' requires master approval"
        )

    new_member = SwarmMember(
        agent_id=agent_id,
        endpoint=agent_endpoint,
        public_key=agent_public_key,
        joined_at=datetime.now(timezone.utc),
    )
    await repo.add_member(claims.swarm_id, new_member)

    updated_swarm = await repo.get_swarm(claims.swarm_id)
    if updated_swarm is None:
        raise SwarmNotFoundError(
            f"Swarm '{claims.swarm_id}' disappeared during join"
        )

    return JoinResult(
        swarm_id=updated_swarm.swarm_id,
        swarm_name=updated_swarm.name,
        members=updated_swarm.members,
    )


async def lookup_swarm(
    conn: aiosqlite.Connection,
    swarm_id: str,
) -> SwarmMembership:
    """Look up a swarm by ID, raising if not found.

    Args:
        conn: Active database connection.
        swarm_id: The swarm identifier.

    Returns:
        The SwarmMembership record.

    Raises:
        SwarmNotFoundError: If the swarm does not exist.
    """
    repo = MembershipRepository(conn)
    swarm = await repo.get_swarm(swarm_id)
    if swarm is None:
        raise SwarmNotFoundError(f"Swarm '{swarm_id}' not found")
    return swarm


async def member_exists(
    conn: aiosqlite.Connection,
    swarm_id: str,
    agent_id: str,
) -> bool:
    """Check whether an agent is already a member of a swarm.

    Args:
        conn: Active database connection.
        swarm_id: The swarm identifier.
        agent_id: The agent identifier.

    Returns:
        True if the agent is a member, False otherwise.
    """
    cursor = await conn.execute(
        "SELECT 1 FROM swarm_members WHERE swarm_id = ? AND agent_id = ?",
        (swarm_id, agent_id),
    )
    row = await cursor.fetchone()
    return row is not None


def _is_member(swarm: SwarmMembership, agent_id: str) -> bool:
    """Check if an agent is in the swarm's member list."""
    return any(m.agent_id == agent_id for m in swarm.members)

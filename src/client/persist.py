"""Persist client swarm membership to the local state database."""

from datetime import datetime, timezone

from src.state.database import DatabaseManager
from src.state.models.member import (
    SwarmMember as StateSwarmMember,
    SwarmMembership as StateSwarmMembership,
    SwarmSettings as StateSwarmSettings,
)
from src.state.repositories.membership import MembershipRepository

from .types import SwarmMembership


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a datetime object.

    Handles timestamps ending in 'Z' (UTC) as well as standard ISO format.

    Args:
        ts: ISO 8601 timestamp string.

    Returns:
        Timezone-aware datetime in UTC.
    """
    cleaned = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
    return datetime.fromisoformat(cleaned)


def _to_state_membership(membership: SwarmMembership) -> StateSwarmMembership:
    """Convert a client SwarmMembership TypedDict to a state SwarmMembership dataclass.

    Args:
        membership: Client-side SwarmMembership TypedDict.

    Returns:
        State-layer SwarmMembership dataclass suitable for database persistence.

    Raises:
        ValueError: If the membership data is invalid.
    """
    settings = membership.get("settings", {})
    members = tuple(
        StateSwarmMember(
            agent_id=m["agent_id"],
            endpoint=m["endpoint"],
            public_key=m["public_key"],
            joined_at=_parse_timestamp(m["joined_at"]),
        )
        for m in membership["members"]
    )
    return StateSwarmMembership(
        swarm_id=membership["swarm_id"],
        name=membership["name"],
        master=membership["master"],
        members=members,
        joined_at=_parse_timestamp(membership["joined_at"]),
        settings=StateSwarmSettings(
            allow_member_invite=settings.get("allow_member_invite", False),
            require_approval=settings.get("require_approval", False),
        ),
    )


async def save_swarm_membership(
    db: DatabaseManager,
    membership: SwarmMembership,
) -> None:
    """Persist a swarm membership to the local database.

    Converts the client-side TypedDict into the state-layer dataclass and
    writes the swarm record plus all members to the database. If the database
    has not been initialized, it is initialized first.

    Args:
        db: The DatabaseManager instance for the local swarm.db.
        membership: Client-side SwarmMembership to persist.

    Raises:
        ValueError: If the membership data cannot be converted.
        DatabaseError: If a database write fails.
    """
    if not db.is_initialized:
        await db.initialize()
    state_membership = _to_state_membership(membership)
    async with db.connection() as conn:
        repo = MembershipRepository(conn)
        existing = await repo.get_swarm(state_membership.swarm_id)
        if existing is None:
            await repo.create_swarm(state_membership)
        else:
            for member in state_membership.members:
                already = any(
                    m.agent_id == member.agent_id for m in existing.members
                )
                if not already:
                    await repo.add_member(state_membership.swarm_id, member)

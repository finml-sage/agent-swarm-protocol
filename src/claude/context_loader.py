"""Context loader for Claude subagent message processing."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.state import (
    DatabaseManager,
    MembershipRepository,
    MessageRepository,
    MuteRepository,
    SwarmMembership,
    QueuedMessage,
)


@dataclass(frozen=True)
class MessageContext:
    """Context for a single incoming message."""

    message_id: str
    swarm_id: str
    sender_id: str
    message_type: str
    content: str
    received_at: datetime

    @classmethod
    def from_queued(cls, msg: QueuedMessage) -> "MessageContext":
        """Create MessageContext from a QueuedMessage."""
        return cls(
            message_id=msg.message_id,
            swarm_id=msg.swarm_id,
            sender_id=msg.sender_id,
            message_type=msg.message_type,
            content=msg.content,
            received_at=msg.received_at,
        )


@dataclass(frozen=True)
class SwarmContext:
    """Full context for Claude subagent processing."""

    message: MessageContext
    swarm: Optional[SwarmMembership]
    recent_messages: tuple[MessageContext, ...]
    is_sender_muted: bool
    is_swarm_muted: bool
    pending_count: int


class ContextLoaderError(Exception):
    """Error loading context for message processing."""


class ContextLoader:
    """Loads full context from state for Claude subagent."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        if not db_manager.is_initialized:
            raise ContextLoaderError("Database not initialized")
        self._db = db_manager

    async def load_context(
        self,
        message: QueuedMessage,
        recent_limit: int = 10,
    ) -> SwarmContext:
        """
        Load full context for processing a message.

        Args:
            message: The queued message to process
            recent_limit: Max number of recent messages to include

        Returns:
            SwarmContext with message, membership, and mute state
        """
        async with self._db.connection() as conn:
            membership_repo = MembershipRepository(conn)
            message_repo = MessageRepository(conn)
            mute_repo = MuteRepository(conn)

            swarm = await membership_repo.get_swarm(message.swarm_id)
            is_sender_muted = await mute_repo.is_agent_muted(message.sender_id)
            is_swarm_muted = await mute_repo.is_swarm_muted(message.swarm_id)
            pending_count = await message_repo.get_pending_count(message.swarm_id)

            recent = await self._get_recent_messages(
                message_repo,
                message.swarm_id,
                recent_limit,
            )

        return SwarmContext(
            message=MessageContext.from_queued(message),
            swarm=swarm,
            recent_messages=recent,
            is_sender_muted=is_sender_muted,
            is_swarm_muted=is_swarm_muted,
            pending_count=pending_count,
        )

    async def _get_recent_messages(
        self,
        repo: MessageRepository,
        swarm_id: str,
        limit: int,
    ) -> tuple[MessageContext, ...]:
        """Get recent completed messages for context."""
        # Note: This would need a get_recent method on MessageRepository
        # For now, we return empty as the repo doesn't support this yet
        # The repository can be extended when needed
        return ()

    async def get_swarm_membership(self, swarm_id: str) -> Optional[SwarmMembership]:
        """Get membership info for a swarm."""
        async with self._db.connection() as conn:
            repo = MembershipRepository(conn)
            return await repo.get_swarm(swarm_id)

    async def get_all_memberships(self) -> list[SwarmMembership]:
        """Get all swarm memberships."""
        async with self._db.connection() as conn:
            repo = MembershipRepository(conn)
            return await repo.get_all_swarms()

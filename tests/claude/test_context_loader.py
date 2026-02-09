"""Tests for context loader."""
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.state import DatabaseManager, InboxRepository, MembershipRepository, MuteRepository
from src.state.models import SwarmMember, SwarmMembership
from src.state.models.inbox import InboxMessage, InboxStatus
from src.claude.context_loader import (
    ContextLoader,
    ContextLoaderError,
    MessageContext,
    SwarmContext,
)


class TestContextLoader:
    """Test context loading functionality."""

    @pytest.fixture
    async def db_manager(self, tmp_path: Path) -> DatabaseManager:
        """Create initialized database manager."""
        db_path = tmp_path / "test.db"
        manager = DatabaseManager(db_path)
        await manager.initialize()
        return manager

    @pytest.fixture
    def sample_message(self) -> InboxMessage:
        """Create sample inbox message."""
        return InboxMessage(
            message_id="msg-123",
            swarm_id="swarm-456",
            sender_id="agent-sender",
            message_type="message",
            content="Hello swarm!",
            received_at=datetime.now(timezone.utc),
            status=InboxStatus.UNREAD,
        )

    @pytest.fixture
    async def sample_swarm(
        self, db_manager: DatabaseManager
    ) -> SwarmMembership:
        """Create sample swarm membership in database."""
        member = SwarmMember(
            agent_id="my-agent",
            endpoint="https://example.com/api",
            public_key="pubkey123",
            joined_at=datetime.now(timezone.utc),
        )
        swarm = SwarmMembership(
            swarm_id="swarm-456",
            name="Test Swarm",
            master="my-agent",
            members=(member,),
            joined_at=datetime.now(timezone.utc),
        )
        async with db_manager.connection() as conn:
            repo = MembershipRepository(conn)
            await repo.create_swarm(swarm)
        return swarm

    def test_uninitialized_db_raises(self, tmp_path: Path) -> None:
        """Uninitialized database should raise error."""
        db = DatabaseManager(tmp_path / "test.db")
        with pytest.raises(ContextLoaderError, match="Database not initialized"):
            ContextLoader(db)

    @pytest.mark.asyncio
    async def test_message_context_from_inbox(
        self, sample_message: InboxMessage
    ) -> None:
        """MessageContext should convert from InboxMessage."""
        ctx = MessageContext.from_inbox(sample_message)
        assert ctx.message_id == sample_message.message_id
        assert ctx.swarm_id == sample_message.swarm_id
        assert ctx.sender_id == sample_message.sender_id
        assert ctx.content == sample_message.content

    @pytest.mark.asyncio
    async def test_load_context_basic(
        self, db_manager: DatabaseManager, sample_message: InboxMessage
    ) -> None:
        """Basic context loading should work."""
        loader = ContextLoader(db_manager)
        context = await loader.load_context(sample_message)

        assert context.message.message_id == sample_message.message_id
        assert context.swarm is None  # No swarm in DB yet
        assert context.is_sender_muted is False
        assert context.is_swarm_muted is False

    @pytest.mark.asyncio
    async def test_load_context_with_swarm(
        self,
        db_manager: DatabaseManager,
        sample_message: InboxMessage,
        sample_swarm: SwarmMembership,
    ) -> None:
        """Context should include swarm membership when exists."""
        loader = ContextLoader(db_manager)
        context = await loader.load_context(sample_message)

        assert context.swarm is not None
        assert context.swarm.name == "Test Swarm"
        assert context.swarm.master == "my-agent"

    @pytest.mark.asyncio
    async def test_load_context_muted_sender(
        self, db_manager: DatabaseManager, sample_message: InboxMessage
    ) -> None:
        """Context should reflect muted sender."""
        async with db_manager.connection() as conn:
            mute_repo = MuteRepository(conn)
            await mute_repo.mute_agent(sample_message.sender_id, reason="spam")

        loader = ContextLoader(db_manager)
        context = await loader.load_context(sample_message)
        assert context.is_sender_muted is True

    @pytest.mark.asyncio
    async def test_load_context_muted_swarm(
        self, db_manager: DatabaseManager, sample_message: InboxMessage
    ) -> None:
        """Context should reflect muted swarm."""
        async with db_manager.connection() as conn:
            mute_repo = MuteRepository(conn)
            await mute_repo.mute_swarm(sample_message.swarm_id, reason="noisy")

        loader = ContextLoader(db_manager)
        context = await loader.load_context(sample_message)
        assert context.is_swarm_muted is True

    @pytest.mark.asyncio
    async def test_get_swarm_membership(
        self,
        db_manager: DatabaseManager,
        sample_swarm: SwarmMembership,
    ) -> None:
        """Should retrieve specific swarm membership."""
        loader = ContextLoader(db_manager)
        swarm = await loader.get_swarm_membership("swarm-456")

        assert swarm is not None
        assert swarm.swarm_id == "swarm-456"
        assert swarm.name == "Test Swarm"

    @pytest.mark.asyncio
    async def test_get_swarm_membership_not_found(
        self, db_manager: DatabaseManager
    ) -> None:
        """Should return None for non-existent swarm."""
        loader = ContextLoader(db_manager)
        swarm = await loader.get_swarm_membership("nonexistent")
        assert swarm is None

    @pytest.mark.asyncio
    async def test_get_all_memberships(
        self,
        db_manager: DatabaseManager,
        sample_swarm: SwarmMembership,
    ) -> None:
        """Should retrieve all swarm memberships."""
        loader = ContextLoader(db_manager)
        swarms = await loader.get_all_memberships()

        assert len(swarms) == 1
        assert swarms[0].swarm_id == "swarm-456"

    @pytest.mark.asyncio
    async def test_load_context_includes_recent_messages(
        self, db_manager: DatabaseManager, sample_message: InboxMessage
    ) -> None:
        """Context should include recent messages from inbox."""
        now = datetime.now(timezone.utc)
        async with db_manager.connection() as conn:
            repo = InboxRepository(conn)
            for i in range(3):
                await repo.insert(InboxMessage(
                    message_id=f"recent-{i}",
                    swarm_id=sample_message.swarm_id,
                    sender_id="other-agent",
                    message_type="message",
                    content=f"Recent message {i}",
                    received_at=now + timedelta(seconds=i),
                ))

        loader = ContextLoader(db_manager)
        context = await loader.load_context(sample_message, recent_limit=10)

        assert len(context.recent_messages) == 3
        # Most recent first
        assert context.recent_messages[0].message_id == "recent-2"
        assert context.recent_messages[2].message_id == "recent-0"
        # All are MessageContext instances
        assert all(isinstance(m, MessageContext) for m in context.recent_messages)

    @pytest.mark.asyncio
    async def test_load_context_recent_messages_respects_limit(
        self, db_manager: DatabaseManager, sample_message: InboxMessage
    ) -> None:
        """Context should respect recent_limit parameter."""
        now = datetime.now(timezone.utc)
        async with db_manager.connection() as conn:
            repo = InboxRepository(conn)
            for i in range(5):
                await repo.insert(InboxMessage(
                    message_id=f"msg-{i}",
                    swarm_id=sample_message.swarm_id,
                    sender_id="other-agent",
                    message_type="message",
                    content=f"Message {i}",
                    received_at=now + timedelta(seconds=i),
                ))

        loader = ContextLoader(db_manager)
        context = await loader.load_context(sample_message, recent_limit=2)

        assert len(context.recent_messages) == 2
        assert context.recent_messages[0].message_id == "msg-4"
        assert context.recent_messages[1].message_id == "msg-3"

    @pytest.mark.asyncio
    async def test_load_context_no_recent_messages(
        self, db_manager: DatabaseManager, sample_message: InboxMessage
    ) -> None:
        """Context should have empty recent_messages when none exist."""
        loader = ContextLoader(db_manager)
        context = await loader.load_context(sample_message)

        assert context.recent_messages == ()

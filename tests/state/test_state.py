"""Tests for state management."""
import pytest, pytest_asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from src.state import DatabaseManager, SwarmMember, SwarmSettings, SwarmMembership, QueuedMessage, MessageStatus, PublicKeyEntry, export_state
from src.state.repositories import MembershipRepository, MessageRepository, MuteRepository, PublicKeyRepository

@pytest_asyncio.fixture
async def db():
    with TemporaryDirectory() as tmpdir:
        manager = DatabaseManager(Path(tmpdir) / "test.db")
        await manager.initialize()
        yield manager

@pytest.fixture
def sample_member(): return SwarmMember(agent_id="test-agent", endpoint="https://test.example.com/swarm", public_key="MCowBQYDK2VwAyEAq9xoSdPXabcdefghijk", joined_at=datetime.now(timezone.utc))

@pytest.fixture
def sample_membership(sample_member): return SwarmMembership(swarm_id="550e8400-e29b-41d4-a716-446655440000", name="Test Swarm", master="test-agent", members=(sample_member,), joined_at=datetime.now(timezone.utc), settings=SwarmSettings(allow_member_invite=False, require_approval=True))

class TestDatabaseManager:
    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, db):
        async with db.connection() as conn:
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in await cursor.fetchall()}
        assert {"schema_versions", "swarms", "swarm_members", "message_queue", "muted_agents", "muted_swarms", "public_keys"}.issubset(tables)

class TestMembershipRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_swarm(self, db, sample_membership):
        async with db.connection() as conn:
            repo = MembershipRepository(conn)
            await repo.create_swarm(sample_membership)
            result = await repo.get_swarm(sample_membership.swarm_id)
        assert result is not None and result.settings.require_approval is True

class TestMessageRepository:
    @pytest.fixture
    def sample_message(self): return QueuedMessage(message_id="msg-001", swarm_id="swarm-001", sender_id="sender-001", message_type="message", content="Hello!", received_at=datetime.now(timezone.utc))

    @pytest.mark.asyncio
    async def test_enqueue_and_complete(self, db, sample_message):
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.enqueue(sample_message)
            await repo.complete(sample_message.message_id)
            msg = await repo.get_by_id(sample_message.message_id)
        assert msg.status == MessageStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_get_recent_returns_completed_messages(self, db):
        """get_recent returns only completed messages ordered by received_at DESC."""
        now = datetime.now(timezone.utc)
        messages = [
            QueuedMessage(message_id=f"msg-{i:03d}", swarm_id="swarm-001", sender_id="sender-001", message_type="message", content=f"Message {i}", received_at=now + timedelta(seconds=i))
            for i in range(5)
        ]
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            for m in messages:
                await repo.enqueue(m)
            # Complete messages 0, 2, 4; leave 1, 3 as pending
            for i in (0, 2, 4):
                await repo.complete(f"msg-{i:03d}")
            result = await repo.get_recent("swarm-001", limit=10)
        assert len(result) == 3
        assert [m.message_id for m in result] == ["msg-004", "msg-002", "msg-000"]
        assert all(m.status == MessageStatus.COMPLETED for m in result)

    @pytest.mark.asyncio
    async def test_get_recent_respects_limit(self, db):
        """get_recent respects the limit parameter."""
        now = datetime.now(timezone.utc)
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            for i in range(5):
                m = QueuedMessage(message_id=f"msg-{i:03d}", swarm_id="swarm-001", sender_id="sender-001", message_type="message", content=f"Message {i}", received_at=now + timedelta(seconds=i))
                await repo.enqueue(m)
                await repo.complete(f"msg-{i:03d}")
            result = await repo.get_recent("swarm-001", limit=2)
        assert len(result) == 2
        assert result[0].message_id == "msg-004"
        assert result[1].message_id == "msg-003"

    @pytest.mark.asyncio
    async def test_get_recent_filters_by_swarm(self, db):
        """get_recent only returns messages for the given swarm_id."""
        now = datetime.now(timezone.utc)
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            for sid in ("swarm-A", "swarm-B"):
                m = QueuedMessage(message_id=f"msg-{sid}", swarm_id=sid, sender_id="sender-001", message_type="message", content="test", received_at=now)
                await repo.enqueue(m)
                await repo.complete(f"msg-{sid}")
            result = await repo.get_recent("swarm-A", limit=10)
        assert len(result) == 1
        assert result[0].swarm_id == "swarm-A"

    @pytest.mark.asyncio
    async def test_get_recent_empty_swarm(self, db):
        """get_recent returns empty list for swarm with no completed messages."""
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            result = await repo.get_recent("nonexistent-swarm", limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_recent_invalid_limit(self, db):
        """get_recent raises ValueError for non-positive limit."""
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            with pytest.raises(ValueError, match="positive integer"):
                await repo.get_recent("swarm-001", limit=0)
            with pytest.raises(ValueError, match="positive integer"):
                await repo.get_recent("swarm-001", limit=-1)

class TestMuteRepository:
    @pytest.mark.asyncio
    async def test_mute_agent(self, db):
        async with db.connection() as conn:
            repo = MuteRepository(conn)
            await repo.mute_agent("spam-agent")
            assert await repo.is_agent_muted("spam-agent")

class TestPublicKeyRepository:
    @pytest.fixture
    def sample_key(self): return PublicKeyEntry(agent_id="test-agent", public_key="MCowBQYDK2VwAyEAq9xoSdPXabcdefghijk", fetched_at=datetime.now(timezone.utc), endpoint="https://test.example.com/swarm/info")

    @pytest.mark.asyncio
    async def test_store_and_get(self, db, sample_key):
        async with db.connection() as conn:
            repo = PublicKeyRepository(conn)
            await repo.store(sample_key)
            result = await repo.get(sample_key.agent_id)
        assert result is not None and result.public_key == sample_key.public_key

class TestExportImport:
    @pytest.mark.asyncio
    async def test_export_state(self, db, sample_membership):
        async with db.connection() as conn:
            await MembershipRepository(conn).create_swarm(sample_membership)
        state = await export_state(db, "my-agent")
        assert state["schema_version"] == "1.0.0" and sample_membership.swarm_id in state["swarms"]

class TestModels:
    def test_swarm_member_requires_https(self):
        with pytest.raises(ValueError, match="HTTPS"): SwarmMember(agent_id="test", endpoint="http://insecure.com", public_key="key", joined_at=datetime.now(timezone.utc))

    def test_queued_message_with_status(self):
        msg = QueuedMessage(message_id="msg-001", swarm_id="swarm-001", sender_id="sender", message_type="message", content="test", received_at=datetime.now(timezone.utc))
        updated = msg.with_status(MessageStatus.COMPLETED)
        assert msg.status == MessageStatus.PENDING and updated.status == MessageStatus.COMPLETED

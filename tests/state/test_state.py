"""Tests for state management."""
import json
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from src.state import (
    DatabaseManager,
    SwarmMember,
    SwarmSettings,
    SwarmMembership,
    QueuedMessage,
    MessageStatus,
    PublicKeyEntry,
    export_state,
)
from src.state.repositories import (
    MembershipRepository,
    MessageRepository,
    MuteRepository,
    PublicKeyRepository,
)


@pytest_asyncio.fixture
async def db():
    with TemporaryDirectory() as tmpdir:
        manager = DatabaseManager(Path(tmpdir) / "test.db")
        await manager.initialize()
        yield manager


@pytest.fixture
def sample_member():
    return SwarmMember(
        agent_id="test-agent",
        endpoint="https://test.example.com/swarm",
        public_key="MCowBQYDK2VwAyEAq9xoSdPXabcdefghijk",
        joined_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_membership(sample_member):
    return SwarmMembership(
        swarm_id="550e8400-e29b-41d4-a716-446655440000",
        name="Test Swarm",
        master="test-agent",
        members=(sample_member,),
        joined_at=datetime.now(timezone.utc),
        settings=SwarmSettings(
            allow_member_invite=False, require_approval=True,
        ),
    )


class TestDatabaseManager:
    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, db):
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        expected = {
            "schema_versions",
            "swarms",
            "swarm_members",
            "message_queue",
            "muted_agents",
            "muted_swarms",
            "public_keys",
        }
        assert expected.issubset(tables)


class TestMembershipRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_swarm(self, db, sample_membership):
        async with db.connection() as conn:
            repo = MembershipRepository(conn)
            await repo.create_swarm(sample_membership)
            result = await repo.get_swarm(sample_membership.swarm_id)
        assert result is not None
        assert result.settings.require_approval is True


class TestMessageRepository:
    @pytest.fixture
    def sample_message(self):
        return QueuedMessage(
            message_id="msg-001",
            swarm_id="swarm-001",
            sender_id="sender-001",
            message_type="message",
            content="Hello!",
            received_at=datetime.now(timezone.utc),
        )

    @pytest.mark.asyncio
    async def test_enqueue_and_complete(self, db, sample_message):
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.enqueue(sample_message)
            await repo.complete(sample_message.message_id)
            msg = await repo.get_by_id(sample_message.message_id)
        assert msg.status == MessageStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_enqueue_stores_all_fields(self, db, sample_message):
        """Verify enqueue persists every field and get_by_id recovers them."""
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.enqueue(sample_message)
            msg = await repo.get_by_id(sample_message.message_id)
        assert msg is not None
        assert msg.message_id == "msg-001"
        assert msg.swarm_id == "swarm-001"
        assert msg.sender_id == "sender-001"
        assert msg.message_type == "message"
        assert msg.content == "Hello!"
        assert msg.status == MessageStatus.PENDING
        assert msg.processed_at is None
        assert msg.error is None

    @pytest.mark.asyncio
    async def test_enqueue_json_content(self, db):
        """Verify JSON payloads survive round-trip through the queue."""
        payload = json.dumps(
            {"type": "message", "text": "hello", "meta": {"k": 1}}
        )
        message = QueuedMessage(
            message_id="msg-json-001",
            swarm_id="swarm-001",
            sender_id="sender-001",
            message_type="message",
            content=payload,
            received_at=datetime.now(timezone.utc),
        )
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.enqueue(message)
            recovered = await repo.get_by_id("msg-json-001")
        assert json.loads(recovered.content) == json.loads(payload)

    @pytest.mark.asyncio
    async def test_claim_next_returns_oldest_pending(self, db):
        """claim_next returns the oldest pending message for a swarm."""
        now = datetime.now(timezone.utc)
        older = QueuedMessage(
            message_id="msg-old",
            swarm_id="swarm-001",
            sender_id="sender",
            message_type="message",
            content="old",
            received_at=now - timedelta(seconds=10),
        )
        newer = QueuedMessage(
            message_id="msg-new",
            swarm_id="swarm-001",
            sender_id="sender",
            message_type="message",
            content="new",
            received_at=now,
        )
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.enqueue(newer)
            await repo.enqueue(older)
            claimed = await repo.claim_next("swarm-001")
        assert claimed is not None
        assert claimed.message_id == "msg-old"

    @pytest.mark.asyncio
    async def test_claim_next_returns_none_when_empty(self, db):
        """claim_next returns None when no pending messages exist."""
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            result = await repo.claim_next("nonexistent-swarm")
        assert result is None

    @pytest.mark.asyncio
    async def test_fail_records_error(self, db, sample_message):
        """fail() sets status to FAILED and records the error string."""
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.enqueue(sample_message)
            result = await repo.fail(sample_message.message_id, "timeout")
            msg = await repo.get_by_id(sample_message.message_id)
        assert result is True
        assert msg.status == MessageStatus.FAILED
        assert msg.error == "timeout"
        assert msg.processed_at is not None

    @pytest.mark.asyncio
    async def test_get_pending_count(self, db):
        """get_pending_count returns only pending messages for the swarm."""
        now = datetime.now(timezone.utc)
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            for i in range(3):
                await repo.enqueue(
                    QueuedMessage(
                        message_id=f"msg-{i}",
                        swarm_id="swarm-001",
                        sender_id="sender",
                        message_type="message",
                        content=f"m{i}",
                        received_at=now,
                    )
                )
            await repo.complete("msg-0")
            count = await repo.get_pending_count("swarm-001")
        assert count == 2

    @pytest.mark.asyncio
    async def test_purge_old_removes_completed(self, db):
        """purge_old removes completed messages older than retention."""
        old_time = datetime.now(timezone.utc) - timedelta(days=10)
        msg = QueuedMessage(
            message_id="msg-old",
            swarm_id="swarm-001",
            sender_id="sender",
            message_type="message",
            content="old",
            received_at=old_time,
        )
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            await repo.enqueue(msg)
            await repo.complete("msg-old")
            # Manually backdate the processed_at so purge catches it
            await conn.execute(
                "UPDATE message_queue SET processed_at = ? WHERE message_id = ?",
                (old_time.isoformat(), "msg-old"),
            )
            await conn.commit()
            purged = await repo.purge_old(retention_days=7)
            remaining = await repo.get_by_id("msg-old")
        assert purged == 1
        assert remaining is None

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_for_missing(self, db):
        """get_by_id returns None for a nonexistent message_id."""
        async with db.connection() as conn:
            repo = MessageRepository(conn)
            result = await repo.get_by_id("nonexistent")
        assert result is None


class TestMuteRepository:
    @pytest.mark.asyncio
    async def test_mute_agent(self, db):
        async with db.connection() as conn:
            repo = MuteRepository(conn)
            await repo.mute_agent("spam-agent")
            assert await repo.is_agent_muted("spam-agent")


class TestPublicKeyRepository:
    @pytest.fixture
    def sample_key(self):
        return PublicKeyEntry(
            agent_id="test-agent",
            public_key="MCowBQYDK2VwAyEAq9xoSdPXabcdefghijk",
            fetched_at=datetime.now(timezone.utc),
            endpoint="https://test.example.com/swarm/info",
        )

    @pytest.mark.asyncio
    async def test_store_and_get(self, db, sample_key):
        async with db.connection() as conn:
            repo = PublicKeyRepository(conn)
            await repo.store(sample_key)
            result = await repo.get(sample_key.agent_id)
        assert result is not None
        assert result.public_key == sample_key.public_key


class TestExportImport:
    @pytest.mark.asyncio
    async def test_export_state(self, db, sample_membership):
        async with db.connection() as conn:
            await MembershipRepository(conn).create_swarm(sample_membership)
        state = await export_state(db, "my-agent")
        assert state["schema_version"] == "1.0.0"
        assert sample_membership.swarm_id in state["swarms"]


class TestModels:
    def test_swarm_member_requires_https(self):
        with pytest.raises(ValueError, match="HTTPS"):
            SwarmMember(
                agent_id="test",
                endpoint="http://insecure.com",
                public_key="key",
                joined_at=datetime.now(timezone.utc),
            )

    def test_queued_message_with_status(self):
        msg = QueuedMessage(
            message_id="msg-001",
            swarm_id="swarm-001",
            sender_id="sender",
            message_type="message",
            content="test",
            received_at=datetime.now(timezone.utc),
        )
        updated = msg.with_status(MessageStatus.COMPLETED)
        assert msg.status == MessageStatus.PENDING
        assert updated.status == MessageStatus.COMPLETED

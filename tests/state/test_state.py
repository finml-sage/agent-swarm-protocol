"""Tests for state management."""
import json
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from src.state import (
    DatabaseManager,
    SwarmMember,
    SwarmSettings,
    SwarmMembership,
    PublicKeyEntry,
    export_state,
)
from src.state.repositories import (
    MembershipRepository,
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
        assert state["schema_version"] == "2.0.0"
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


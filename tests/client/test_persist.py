"""Tests for swarm membership persistence after join."""

from pathlib import Path
from uuid import uuid4

import pytest

from src.client.persist import save_swarm_membership, _to_state_membership
from src.client.types import SwarmMember, SwarmMembership, SwarmSettings
from src.state.database import DatabaseManager
from src.state.repositories.membership import MembershipRepository


def _make_membership(
    swarm_id: str | None = None,
    name: str = "Test Swarm",
    master: str = "master-agent",
    members: list[SwarmMember] | None = None,
) -> SwarmMembership:
    """Build a SwarmMembership TypedDict for testing."""
    sid = swarm_id or str(uuid4())
    now = "2026-01-15T12:00:00.000Z"
    if members is None:
        members = [
            SwarmMember(
                agent_id="master-agent",
                endpoint="https://master.example.com/swarm",
                public_key="AAAA" + "A" * 39 + "=",
                joined_at=now,
            ),
        ]
    return SwarmMembership(
        swarm_id=sid,
        name=name,
        master=master,
        members=members,
        joined_at=now,
        settings=SwarmSettings(
            allow_member_invite=False,
            require_approval=False,
        ),
    )


class TestToStateMembership:
    def test_converts_basic_membership(self) -> None:
        m = _make_membership()
        state = _to_state_membership(m)
        assert state.swarm_id == m["swarm_id"]
        assert state.name == "Test Swarm"
        assert state.master == "master-agent"
        assert len(state.members) == 1
        assert state.members[0].agent_id == "master-agent"

    def test_converts_settings(self) -> None:
        m = _make_membership()
        m["settings"]["allow_member_invite"] = True
        state = _to_state_membership(m)
        assert state.settings.allow_member_invite is True
        assert state.settings.require_approval is False

    def test_converts_timestamp_with_z_suffix(self) -> None:
        m = _make_membership()
        state = _to_state_membership(m)
        assert state.joined_at.tzinfo is not None
        assert state.members[0].joined_at.tzinfo is not None


class TestSaveSwarmMembership:
    @pytest.fixture
    async def db(self, tmp_path: Path) -> DatabaseManager:
        """Create an initialized in-memory database manager."""
        db_mgr = DatabaseManager(tmp_path / "test_swarm.db")
        await db_mgr.initialize()
        return db_mgr

    @pytest.mark.asyncio
    async def test_saves_swarm_and_members(self, db: DatabaseManager) -> None:
        m = _make_membership()
        await save_swarm_membership(db, m)

        async with db.connection() as conn:
            repo = MembershipRepository(conn)
            saved = await repo.get_swarm(m["swarm_id"])

        assert saved is not None
        assert saved.swarm_id == m["swarm_id"]
        assert saved.name == "Test Swarm"
        assert saved.master == "master-agent"
        assert len(saved.members) == 1
        assert saved.members[0].agent_id == "master-agent"

    @pytest.mark.asyncio
    async def test_saves_multiple_members(self, db: DatabaseManager) -> None:
        now = "2026-01-15T12:00:00.000Z"
        members = [
            SwarmMember(
                agent_id="master-agent",
                endpoint="https://master.example.com/swarm",
                public_key="AAAA" + "A" * 39 + "=",
                joined_at=now,
            ),
            SwarmMember(
                agent_id="joiner-agent",
                endpoint="https://joiner.example.com/swarm",
                public_key="BBBB" + "B" * 39 + "=",
                joined_at=now,
            ),
        ]
        m = _make_membership(members=members)
        await save_swarm_membership(db, m)

        async with db.connection() as conn:
            repo = MembershipRepository(conn)
            saved = await repo.get_swarm(m["swarm_id"])

        assert saved is not None
        assert len(saved.members) == 2
        agent_ids = {mem.agent_id for mem in saved.members}
        assert agent_ids == {"master-agent", "joiner-agent"}

    @pytest.mark.asyncio
    async def test_idempotent_save(self, db: DatabaseManager) -> None:
        """Saving the same membership twice should not raise or duplicate."""
        m = _make_membership()
        await save_swarm_membership(db, m)
        await save_swarm_membership(db, m)

        async with db.connection() as conn:
            repo = MembershipRepository(conn)
            saved = await repo.get_swarm(m["swarm_id"])

        assert saved is not None
        assert len(saved.members) == 1

    @pytest.mark.asyncio
    async def test_initializes_db_if_needed(self, tmp_path: Path) -> None:
        """Database should be auto-initialized if not already."""
        db_mgr = DatabaseManager(tmp_path / "uninit_swarm.db")
        assert not db_mgr.is_initialized

        m = _make_membership()
        await save_swarm_membership(db_mgr, m)

        assert db_mgr.is_initialized
        async with db_mgr.connection() as conn:
            repo = MembershipRepository(conn)
            saved = await repo.get_swarm(m["swarm_id"])
        assert saved is not None

    @pytest.mark.asyncio
    async def test_adds_new_members_to_existing_swarm(self, db: DatabaseManager) -> None:
        """When a swarm already exists, new members should be added without error."""
        now = "2026-01-15T12:00:00.000Z"
        m1 = _make_membership()
        await save_swarm_membership(db, m1)

        new_member = SwarmMember(
            agent_id="new-agent",
            endpoint="https://new.example.com/swarm",
            public_key="CCCC" + "C" * 39 + "=",
            joined_at=now,
        )
        m2 = _make_membership(
            swarm_id=m1["swarm_id"],
            members=m1["members"] + [new_member],
        )
        await save_swarm_membership(db, m2)

        async with db.connection() as conn:
            repo = MembershipRepository(conn)
            saved = await repo.get_swarm(m1["swarm_id"])

        assert saved is not None
        assert len(saved.members) == 2
        agent_ids = {mem.agent_id for mem in saved.members}
        assert "new-agent" in agent_ids

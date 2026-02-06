"""Tests for SDK session persistence and conversation continuity."""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.state.database import DatabaseManager
from src.state.models.session import SdkSession
from src.state.repositories.sessions import SessionRepository
from src.state.session_service import lookup_sdk_session, persist_sdk_session


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> DatabaseManager:
    """Create and initialize an in-memory-like temp database."""
    db_manager = DatabaseManager(tmp_path / "test_sessions.db")
    await db_manager.initialize()
    return db_manager


class TestSdkSessionModel:
    """Tests for the SdkSession frozen dataclass."""

    def test_create_valid_session(self) -> None:
        now = datetime.now(timezone.utc)
        s = SdkSession(
            swarm_id="swarm-1", peer_id="peer-1",
            session_id="sess-abc", last_active=now,
        )
        assert s.swarm_id == "swarm-1"
        assert s.peer_id == "peer-1"
        assert s.session_id == "sess-abc"
        assert s.state == "active"

    def test_empty_swarm_id_raises(self) -> None:
        with pytest.raises(ValueError, match="swarm_id"):
            SdkSession(
                swarm_id="", peer_id="p", session_id="s",
                last_active=datetime.now(timezone.utc),
            )

    def test_empty_peer_id_raises(self) -> None:
        with pytest.raises(ValueError, match="peer_id"):
            SdkSession(
                swarm_id="sw", peer_id="", session_id="s",
                last_active=datetime.now(timezone.utc),
            )

    def test_empty_session_id_raises(self) -> None:
        with pytest.raises(ValueError, match="session_id"):
            SdkSession(
                swarm_id="sw", peer_id="p", session_id="",
                last_active=datetime.now(timezone.utc),
            )

    def test_is_expired_false_within_timeout(self) -> None:
        s = SdkSession(
            swarm_id="sw", peer_id="p", session_id="s",
            last_active=datetime.now(timezone.utc),
        )
        assert s.is_expired(timeout_minutes=30) is False

    def test_is_expired_true_beyond_timeout(self) -> None:
        old = datetime.now(timezone.utc) - timedelta(minutes=60)
        s = SdkSession(
            swarm_id="sw", peer_id="p", session_id="s",
            last_active=old,
        )
        assert s.is_expired(timeout_minutes=30) is True

    def test_frozen(self) -> None:
        s = SdkSession(
            swarm_id="sw", peer_id="p", session_id="s",
            last_active=datetime.now(timezone.utc),
        )
        with pytest.raises(AttributeError):
            s.session_id = "other"  # type: ignore[misc]


class TestSessionRepository:
    """Tests for SessionRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_upsert_and_get(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = SessionRepository(conn)
            session = SdkSession(
                swarm_id="sw-1", peer_id="peer-a",
                session_id="sess-123",
                last_active=datetime.now(timezone.utc),
            )
            await repo.upsert(session)
            result = await repo.get("sw-1", "peer-a")
        assert result is not None
        assert result.session_id == "sess-123"

    @pytest.mark.asyncio
    async def test_upsert_replaces_existing(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = SessionRepository(conn)
            now = datetime.now(timezone.utc)
            s1 = SdkSession(
                swarm_id="sw-1", peer_id="peer-a",
                session_id="old-sess", last_active=now,
            )
            await repo.upsert(s1)
            s2 = SdkSession(
                swarm_id="sw-1", peer_id="peer-a",
                session_id="new-sess", last_active=now,
            )
            await repo.upsert(s2)
            result = await repo.get("sw-1", "peer-a")
        assert result is not None
        assert result.session_id == "new-sess"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(
        self, db: DatabaseManager,
    ) -> None:
        async with db.connection() as conn:
            repo = SessionRepository(conn)
            result = await repo.get("no-swarm", "no-peer")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_returns_fresh_session(
        self, db: DatabaseManager,
    ) -> None:
        async with db.connection() as conn:
            repo = SessionRepository(conn)
            session = SdkSession(
                swarm_id="sw-1", peer_id="peer-a",
                session_id="sess-fresh",
                last_active=datetime.now(timezone.utc),
            )
            await repo.upsert(session)
            result = await repo.get_active("sw-1", "peer-a", 30)
        assert result is not None
        assert result.session_id == "sess-fresh"

    @pytest.mark.asyncio
    async def test_get_active_returns_none_for_expired(
        self, db: DatabaseManager,
    ) -> None:
        old = datetime.now(timezone.utc) - timedelta(minutes=60)
        async with db.connection() as conn:
            repo = SessionRepository(conn)
            session = SdkSession(
                swarm_id="sw-1", peer_id="peer-a",
                session_id="sess-old", last_active=old,
            )
            await repo.upsert(session)
            result = await repo.get_active("sw-1", "peer-a", 30)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_deletes_expired(
        self, db: DatabaseManager,
    ) -> None:
        old = datetime.now(timezone.utc) - timedelta(minutes=60)
        async with db.connection() as conn:
            repo = SessionRepository(conn)
            session = SdkSession(
                swarm_id="sw-1", peer_id="peer-a",
                session_id="sess-old", last_active=old,
            )
            await repo.upsert(session)
            await repo.get_active("sw-1", "peer-a", 30)
            raw = await repo.get("sw-1", "peer-a")
        assert raw is None

    @pytest.mark.asyncio
    async def test_delete(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = SessionRepository(conn)
            session = SdkSession(
                swarm_id="sw-1", peer_id="peer-a",
                session_id="sess-del",
                last_active=datetime.now(timezone.utc),
            )
            await repo.upsert(session)
            deleted = await repo.delete("sw-1", "peer-a")
        assert deleted is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_missing(
        self, db: DatabaseManager,
    ) -> None:
        async with db.connection() as conn:
            repo = SessionRepository(conn)
            deleted = await repo.delete("no-swarm", "no-peer")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_per_swarm_isolation(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = SessionRepository(conn)
            now = datetime.now(timezone.utc)
            s1 = SdkSession(
                swarm_id="sw-1", peer_id="peer-a",
                session_id="sess-sw1", last_active=now,
            )
            s2 = SdkSession(
                swarm_id="sw-2", peer_id="peer-a",
                session_id="sess-sw2", last_active=now,
            )
            await repo.upsert(s1)
            await repo.upsert(s2)
            r1 = await repo.get("sw-1", "peer-a")
            r2 = await repo.get("sw-2", "peer-a")
        assert r1 is not None and r1.session_id == "sess-sw1"
        assert r2 is not None and r2.session_id == "sess-sw2"


class TestSessionService:
    """Tests for the session service convenience functions."""

    @pytest.mark.asyncio
    async def test_persist_and_lookup(self, db: DatabaseManager) -> None:
        await persist_sdk_session(db, "sw-1", "peer-a", "sess-new")
        result = await lookup_sdk_session(db, "sw-1", "peer-a", 30)
        assert result == "sess-new"

    @pytest.mark.asyncio
    async def test_lookup_returns_none_when_empty(
        self, db: DatabaseManager,
    ) -> None:
        result = await lookup_sdk_session(db, "sw-1", "peer-a", 30)
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_returns_none_when_expired(
        self, db: DatabaseManager,
    ) -> None:
        await persist_sdk_session(db, "sw-1", "peer-a", "sess-old")
        result = await lookup_sdk_session(db, "sw-1", "peer-a", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_persist_overwrites_previous(
        self, db: DatabaseManager,
    ) -> None:
        await persist_sdk_session(db, "sw-1", "peer-a", "sess-1")
        await persist_sdk_session(db, "sw-1", "peer-a", "sess-2")
        result = await lookup_sdk_session(db, "sw-1", "peer-a", 30)
        assert result == "sess-2"

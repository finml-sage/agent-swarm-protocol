"""Tests for outbox model and repository."""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.state.database import DatabaseManager
from src.state.models.outbox import OutboxMessage, OutboxStatus
from src.state.repositories.outbox import OutboxRepository


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> DatabaseManager:
    """Create and initialize a temp database."""
    manager = DatabaseManager(tmp_path / "test_outbox.db")
    await manager.initialize()
    return manager


def _msg(
    msg_id: str = "out-001",
    swarm_id: str = "swarm-1",
    recipient_id: str = "recipient-1",
    **kwargs,
) -> OutboxMessage:
    """Helper to build an OutboxMessage with defaults."""
    defaults = dict(
        message_id=msg_id,
        swarm_id=swarm_id,
        recipient_id=recipient_id,
        message_type="message",
        content="Hello outbox",
        sent_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return OutboxMessage(**defaults)


class TestOutboxModel:
    """Tests for the OutboxMessage frozen dataclass."""

    def test_create_valid(self) -> None:
        m = _msg()
        assert m.status == OutboxStatus.SENT
        assert m.error is None

    def test_empty_message_id_raises(self) -> None:
        with pytest.raises(ValueError, match="message_id"):
            _msg(msg_id="")

    def test_empty_swarm_id_raises(self) -> None:
        with pytest.raises(ValueError, match="swarm_id"):
            _msg(swarm_id="")

    def test_empty_recipient_id_raises(self) -> None:
        with pytest.raises(ValueError, match="recipient_id"):
            _msg(recipient_id="")

    def test_empty_message_type_raises(self) -> None:
        with pytest.raises(ValueError, match="message_type"):
            _msg(message_type="")

    def test_frozen(self) -> None:
        m = _msg()
        with pytest.raises(AttributeError):
            m.status = OutboxStatus.DELIVERED  # type: ignore[misc]

    def test_status_enum_values(self) -> None:
        assert OutboxStatus.SENT.value == "sent"
        assert OutboxStatus.DELIVERED.value == "delivered"
        assert OutboxStatus.FAILED.value == "failed"


class TestOutboxRepository:
    """Tests for OutboxRepository operations."""

    @pytest.mark.asyncio
    async def test_insert_and_list(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            await repo.insert(_msg())
            result = await repo.list_by_swarm("swarm-1")
        assert len(result) == 1
        assert result[0].message_id == "out-001"

    @pytest.mark.asyncio
    async def test_list_by_swarm_ordering(self, db: DatabaseManager) -> None:
        now = datetime.now(timezone.utc)
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            for i in range(3):
                await repo.insert(
                    _msg(
                        msg_id=f"out-{i}",
                        sent_at=now + timedelta(seconds=i),
                    )
                )
            result = await repo.list_by_swarm("swarm-1")
        assert [m.message_id for m in result] == ["out-2", "out-1", "out-0"]

    @pytest.mark.asyncio
    async def test_list_by_swarm_respects_limit(
        self, db: DatabaseManager
    ) -> None:
        now = datetime.now(timezone.utc)
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            for i in range(5):
                await repo.insert(
                    _msg(
                        msg_id=f"out-{i}",
                        sent_at=now + timedelta(seconds=i),
                    )
                )
            result = await repo.list_by_swarm("swarm-1", limit=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_by_swarm_invalid_limit(
        self, db: DatabaseManager
    ) -> None:
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            with pytest.raises(ValueError, match="positive integer"):
                await repo.list_by_swarm("swarm-1", limit=0)

    @pytest.mark.asyncio
    async def test_list_by_swarm_filters(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            await repo.insert(_msg(msg_id="out-a", swarm_id="swarm-a"))
            await repo.insert(_msg(msg_id="out-b", swarm_id="swarm-b"))
            result = await repo.list_by_swarm("swarm-a")
        assert len(result) == 1
        assert result[0].swarm_id == "swarm-a"

    @pytest.mark.asyncio
    async def test_count_by_swarm(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            for i in range(3):
                await repo.insert(_msg(msg_id=f"out-{i}"))
            await repo.mark_delivered("out-0")
            await repo.mark_failed("out-1", "timeout")
            counts = await repo.count_by_swarm("swarm-1")
        assert counts["sent"] == 1
        assert counts["delivered"] == 1
        assert counts["failed"] == 1
        assert counts["total"] == 3

    @pytest.mark.asyncio
    async def test_mark_delivered(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            await repo.insert(_msg())
            updated = await repo.mark_delivered("out-001")
            result = await repo.list_by_swarm("swarm-1")
        assert updated is True
        assert result[0].status == OutboxStatus.DELIVERED

    @pytest.mark.asyncio
    async def test_mark_delivered_already_delivered(
        self, db: DatabaseManager
    ) -> None:
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            await repo.insert(_msg())
            await repo.mark_delivered("out-001")
            updated = await repo.mark_delivered("out-001")
        assert updated is False

    @pytest.mark.asyncio
    async def test_mark_failed(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            await repo.insert(_msg())
            updated = await repo.mark_failed("out-001", "connection refused")
            result = await repo.list_by_swarm("swarm-1")
        assert updated is True
        assert result[0].status == OutboxStatus.FAILED
        assert result[0].error == "connection refused"

    @pytest.mark.asyncio
    async def test_mark_failed_already_failed(
        self, db: DatabaseManager
    ) -> None:
        async with db.connection() as conn:
            repo = OutboxRepository(conn)
            await repo.insert(_msg())
            await repo.mark_failed("out-001", "error1")
            updated = await repo.mark_failed("out-001", "error2")
        assert updated is False

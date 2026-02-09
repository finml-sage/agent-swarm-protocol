"""Tests for inbox model and repository."""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.state.database import DatabaseManager
from src.state.models.inbox import InboxMessage, InboxStatus
from src.state.repositories.inbox import InboxRepository


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> DatabaseManager:
    """Create and initialize a temp database."""
    manager = DatabaseManager(tmp_path / "test_inbox.db")
    await manager.initialize()
    return manager


def _msg(
    msg_id: str = "msg-001",
    swarm_id: str = "swarm-1",
    sender_id: str = "sender-1",
    **kwargs,
) -> InboxMessage:
    """Helper to build an InboxMessage with defaults."""
    defaults = dict(
        message_id=msg_id,
        swarm_id=swarm_id,
        sender_id=sender_id,
        message_type="message",
        content="Hello",
        received_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return InboxMessage(**defaults)


class TestInboxModel:
    """Tests for the InboxMessage frozen dataclass."""

    def test_create_valid(self) -> None:
        m = _msg()
        assert m.status == InboxStatus.UNREAD
        assert m.read_at is None
        assert m.recipient_id is None

    def test_empty_message_id_raises(self) -> None:
        with pytest.raises(ValueError, match="message_id"):
            _msg(msg_id="")

    def test_empty_swarm_id_raises(self) -> None:
        with pytest.raises(ValueError, match="swarm_id"):
            _msg(swarm_id="")

    def test_empty_sender_id_raises(self) -> None:
        with pytest.raises(ValueError, match="sender_id"):
            _msg(sender_id="")

    def test_empty_message_type_raises(self) -> None:
        with pytest.raises(ValueError, match="message_type"):
            _msg(message_type="")

    def test_frozen(self) -> None:
        m = _msg()
        with pytest.raises(AttributeError):
            m.status = InboxStatus.READ  # type: ignore[misc]

    def test_status_enum_values(self) -> None:
        assert InboxStatus.UNREAD.value == "unread"
        assert InboxStatus.READ.value == "read"
        assert InboxStatus.ARCHIVED.value == "archived"
        assert InboxStatus.DELETED.value == "deleted"


class TestInboxRepository:
    """Tests for InboxRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_insert_and_get_by_id(self, db: DatabaseManager) -> None:
        msg = _msg()
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(msg)
            result = await repo.get_by_id("msg-001")
        assert result is not None
        assert result.message_id == "msg-001"
        assert result.status == InboxStatus.UNREAD

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            result = await repo.get_by_id("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_mark_read(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(_msg())
            updated = await repo.mark_read("msg-001")
            result = await repo.get_by_id("msg-001")
        assert updated is True
        assert result.status == InboxStatus.READ
        assert result.read_at is not None

    @pytest.mark.asyncio
    async def test_mark_read_already_read(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(_msg())
            await repo.mark_read("msg-001")
            updated = await repo.mark_read("msg-001")
        assert updated is False

    @pytest.mark.asyncio
    async def test_mark_archived_from_unread(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(_msg())
            updated = await repo.mark_archived("msg-001")
            result = await repo.get_by_id("msg-001")
        assert updated is True
        assert result.status == InboxStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_mark_archived_from_read(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(_msg())
            await repo.mark_read("msg-001")
            updated = await repo.mark_archived("msg-001")
            result = await repo.get_by_id("msg-001")
        assert updated is True
        assert result.status == InboxStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_mark_archived_already_deleted(
        self, db: DatabaseManager
    ) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(_msg())
            await repo.mark_deleted("msg-001")
            updated = await repo.mark_archived("msg-001")
        assert updated is False

    @pytest.mark.asyncio
    async def test_mark_deleted(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(_msg())
            updated = await repo.mark_deleted("msg-001")
            result = await repo.get_by_id("msg-001")
        assert updated is True
        assert result.status == InboxStatus.DELETED

    @pytest.mark.asyncio
    async def test_mark_deleted_already_deleted(
        self, db: DatabaseManager
    ) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(_msg())
            await repo.mark_deleted("msg-001")
            updated = await repo.mark_deleted("msg-001")
        assert updated is False

    @pytest.mark.asyncio
    async def test_list_by_status(self, db: DatabaseManager) -> None:
        now = datetime.now(timezone.utc)
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            for i in range(3):
                await repo.insert(
                    _msg(
                        msg_id=f"msg-{i}",
                        received_at=now + timedelta(seconds=i),
                    )
                )
            await repo.mark_read("msg-1")
            unread = await repo.list_by_status("swarm-1", InboxStatus.UNREAD)
            read = await repo.list_by_status("swarm-1", InboxStatus.READ)
        assert len(unread) == 2
        assert len(read) == 1

    @pytest.mark.asyncio
    async def test_list_by_status_respects_limit(
        self, db: DatabaseManager
    ) -> None:
        now = datetime.now(timezone.utc)
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            for i in range(5):
                await repo.insert(
                    _msg(
                        msg_id=f"msg-{i}",
                        received_at=now + timedelta(seconds=i),
                    )
                )
            result = await repo.list_by_status(
                "swarm-1", InboxStatus.UNREAD, limit=2
            )
        assert len(result) == 2
        assert result[0].message_id == "msg-4"

    @pytest.mark.asyncio
    async def test_list_by_status_invalid_limit(
        self, db: DatabaseManager
    ) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            with pytest.raises(ValueError, match="positive integer"):
                await repo.list_by_status("swarm-1", InboxStatus.UNREAD, limit=0)

    @pytest.mark.asyncio
    async def test_count_by_status(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            for i in range(4):
                await repo.insert(_msg(msg_id=f"msg-{i}"))
            await repo.mark_read("msg-0")
            await repo.mark_archived("msg-1")
            counts = await repo.count_by_status("swarm-1")
        assert counts["unread"] == 2
        assert counts["read"] == 1
        assert counts["archived"] == 1
        assert counts["deleted"] == 0
        assert counts["total"] == 4

    @pytest.mark.asyncio
    async def test_batch_update_status(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            for i in range(3):
                await repo.insert(_msg(msg_id=f"msg-{i}"))
            updated = await repo.batch_update_status(
                ["msg-0", "msg-1"], InboxStatus.READ
            )
            m0 = await repo.get_by_id("msg-0")
            m1 = await repo.get_by_id("msg-1")
            m2 = await repo.get_by_id("msg-2")
        assert updated == 2
        assert m0.status == InboxStatus.READ
        assert m1.status == InboxStatus.READ
        assert m2.status == InboxStatus.UNREAD

    @pytest.mark.asyncio
    async def test_batch_update_empty_list(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            updated = await repo.batch_update_status([], InboxStatus.READ)
        assert updated == 0

    @pytest.mark.asyncio
    async def test_purge_deleted(self, db: DatabaseManager) -> None:
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            for i in range(3):
                await repo.insert(_msg(msg_id=f"msg-{i}"))
            await repo.mark_deleted("msg-0")
            await repo.mark_deleted("msg-1")
            purged = await repo.purge_deleted()
            remaining = await repo.get_by_id("msg-0")
            kept = await repo.get_by_id("msg-2")
        assert purged == 2
        assert remaining is None
        assert kept is not None

    @pytest.mark.asyncio
    async def test_insert_with_recipient(self, db: DatabaseManager) -> None:
        msg = _msg(recipient_id="recipient-1")
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            await repo.insert(msg)
            result = await repo.get_by_id("msg-001")
        assert result.recipient_id == "recipient-1"

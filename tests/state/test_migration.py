"""Tests for schema migration from 1.0.0 to 2.0.0."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from pathlib import Path

from src.state.database import DatabaseManager


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> DatabaseManager:
    """Create and initialize a temp database."""
    manager = DatabaseManager(tmp_path / "test_migration.db")
    await manager.initialize()
    return manager


class TestMigration:
    """Tests for the 1.0.0 -> 2.0.0 inbox/outbox migration."""

    @pytest.mark.asyncio
    async def test_fresh_db_has_inbox_outbox(self, db: DatabaseManager) -> None:
        """A fresh initialize() creates inbox and outbox tables."""
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        assert "inbox" in tables
        assert "outbox" in tables

    @pytest.mark.asyncio
    async def test_schema_version_2_0_0(self, db: DatabaseManager) -> None:
        """After initialize(), schema_versions contains 2.0.0."""
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT version FROM schema_versions ORDER BY version"
            )
            versions = [row[0] for row in await cursor.fetchall()]
        assert "1.0.0" in versions
        assert "2.0.0" in versions

    @pytest.mark.asyncio
    async def test_migration_copies_pending_as_unread(
        self, tmp_path: Path
    ) -> None:
        """Pending message_queue rows migrate to inbox as unread."""
        db_path = tmp_path / "migrate_pending.db"
        manager = DatabaseManager(db_path)
        # First pass: create v1.0.0 schema with a pending message
        manager._db_path.parent.mkdir(parents=True, exist_ok=True)
        import aiosqlite

        conn = await aiosqlite.connect(db_path)
        # Create only the v1 schema (no migration)
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_versions (
                version TEXT PRIMARY KEY, applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS message_queue (
                message_id TEXT PRIMARY KEY,
                swarm_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                received_at TEXT NOT NULL,
                processed_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT
            );
            INSERT OR IGNORE INTO schema_versions VALUES ('1.0.0', datetime('now'));
            INSERT INTO message_queue VALUES (
                'msg-pending', 'swarm-1', 'sender-1', 'message',
                'Hello pending', '2026-01-01T00:00:00+00:00',
                NULL, 'pending', NULL
            );
            INSERT INTO message_queue VALUES (
                'msg-completed', 'swarm-1', 'sender-1', 'message',
                'Hello completed', '2026-01-01T00:00:01+00:00',
                '2026-01-01T00:00:02+00:00', 'completed', NULL
            );
            INSERT INTO message_queue VALUES (
                'msg-failed', 'swarm-1', 'sender-1', 'message',
                'Hello failed', '2026-01-01T00:00:03+00:00',
                '2026-01-01T00:00:04+00:00', 'failed', 'oops'
            );
            """
        )
        await conn.commit()
        await conn.close()

        # Now initialize with migration
        await manager.initialize()

        async with manager.connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT message_id, status FROM inbox ORDER BY message_id"
            )
            rows = await cursor.fetchall()

        by_id = {row["message_id"]: row["status"] for row in rows}
        assert by_id["msg-pending"] == "unread"
        assert by_id["msg-completed"] == "read"
        assert by_id["msg-failed"] == "read"

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, db: DatabaseManager) -> None:
        """Running initialize() twice does not duplicate inbox rows."""
        async with db.connection() as conn:
            await conn.execute(
                "INSERT INTO inbox VALUES "
                "('msg-test', 'swarm-1', 'sender-1', NULL, 'message', "
                "'content', '2026-01-01T00:00:00+00:00', NULL, 'unread')"
            )
            await conn.commit()

        # Re-initialize (triggers migration check again)
        await db.initialize()

        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM inbox WHERE message_id = 'msg-test'"
            )
            count = (await cursor.fetchone())[0]
        assert count == 1

    @pytest.mark.asyncio
    async def test_message_queue_preserved(self, db: DatabaseManager) -> None:
        """The old message_queue table is kept (not dropped)."""
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='message_queue'"
            )
            row = await cursor.fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_inbox_indexes_created(self, db: DatabaseManager) -> None:
        """Inbox indexes are created during migration."""
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            indexes = {row[0] for row in await cursor.fetchall()}
        assert "idx_inbox_status" in indexes
        assert "idx_inbox_swarm" in indexes
        assert "idx_inbox_sender" in indexes

    @pytest.mark.asyncio
    async def test_outbox_indexes_created(self, db: DatabaseManager) -> None:
        """Outbox indexes are created during migration."""
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            indexes = {row[0] for row in await cursor.fetchall()}
        assert "idx_outbox_swarm" in indexes
        assert "idx_outbox_sent" in indexes

    @pytest.mark.asyncio
    async def test_inbox_check_constraint(self, db: DatabaseManager) -> None:
        """Inbox status CHECK constraint rejects invalid values."""
        async with db.connection() as conn:
            with pytest.raises(Exception):
                await conn.execute(
                    "INSERT INTO inbox VALUES "
                    "('bad', 'sw', 'sn', NULL, 'msg', 'c', "
                    "'2026-01-01T00:00:00+00:00', NULL, 'INVALID')"
                )

    @pytest.mark.asyncio
    async def test_outbox_check_constraint(self, db: DatabaseManager) -> None:
        """Outbox status CHECK constraint rejects invalid values."""
        async with db.connection() as conn:
            with pytest.raises(Exception):
                await conn.execute(
                    "INSERT INTO outbox VALUES "
                    "('bad', 'sw', 'rcp', 'msg', 'c', "
                    "'2026-01-01T00:00:00+00:00', 'INVALID', NULL)"
                )

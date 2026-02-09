"""Database connection and lifecycle management."""
import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator


class DatabaseError(Exception):
    pass


class DatabaseManager:
    """Manages SQLite database connections and schema initialization."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._initialized = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def initialize(self) -> None:
        """Create tables, indexes, and run migrations."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connection() as conn:
            await conn.executescript(_SCHEMA)
            await conn.commit()
            await _migrate_to_2_0_0(conn)
            await _migrate_to_2_1_0(conn)
        self._initialized = True

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Yield an async database connection."""
        conn = await aiosqlite.connect(self._db_path)
        conn.row_factory = aiosqlite.Row
        try:
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            await conn.close()

    async def close(self) -> None:
        """Mark the manager as closed."""
        self._initialized = False


async def _migrate_to_2_0_0(conn: aiosqlite.Connection) -> None:
    """Migrate from schema 1.0.0 to 2.0.0: add inbox/outbox tables.

    Idempotent -- checks schema_versions before running.  Creates the
    inbox and outbox tables, copies existing message_queue rows into
    inbox with status mapping, and records the new version.
    """
    cursor = await conn.execute(
        "SELECT 1 FROM schema_versions WHERE version = '2.0.0'"
    )
    if await cursor.fetchone() is not None:
        return

    await conn.executescript(_INBOX_OUTBOX_DDL)

    # Migrate existing message_queue rows into inbox.
    # Status mapping: pending/processing -> unread, completed -> read,
    # failed -> read (preserves visibility).
    await conn.execute(
        "INSERT OR IGNORE INTO inbox "
        "(message_id, swarm_id, sender_id, recipient_id, "
        "message_type, content, received_at, read_at, status) "
        "SELECT message_id, swarm_id, sender_id, NULL, "
        "message_type, content, received_at, processed_at, "
        "CASE "
        "  WHEN status IN ('pending', 'processing') THEN 'unread' "
        "  WHEN status = 'completed' THEN 'read' "
        "  WHEN status = 'failed' THEN 'read' "
        "  ELSE 'unread' "
        "END "
        "FROM message_queue"
    )

    await conn.execute(
        "INSERT OR IGNORE INTO schema_versions (version, applied_at) "
        "VALUES ('2.0.0', datetime('now'))"
    )
    await conn.commit()


async def _migrate_to_2_1_0(conn: aiosqlite.Connection) -> None:
    """Migrate from 2.0.0 to 2.1.0: add deleted_at column to inbox.

    Idempotent -- checks schema_versions before running.  Also checks
    whether the column already exists (e.g. fresh databases created with
    the updated DDL).
    """
    cursor = await conn.execute(
        "SELECT 1 FROM schema_versions WHERE version = '2.1.0'"
    )
    if await cursor.fetchone() is not None:
        return

    # Check if deleted_at column already exists (fresh DB has it in DDL)
    col_cursor = await conn.execute("PRAGMA table_info(inbox)")
    columns = {row[1] for row in await col_cursor.fetchall()}
    if "deleted_at" not in columns:
        await conn.execute("ALTER TABLE inbox ADD COLUMN deleted_at TEXT")

    await conn.execute(
        "INSERT OR IGNORE INTO schema_versions (version, applied_at) "
        "VALUES ('2.1.0', datetime('now'))"
    )
    await conn.commit()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS swarms (swarm_id TEXT PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) <= 256), master TEXT NOT NULL, joined_at TEXT NOT NULL, allow_member_invite INTEGER NOT NULL DEFAULT 0, require_approval INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS swarm_members (agent_id TEXT NOT NULL, swarm_id TEXT NOT NULL, endpoint TEXT NOT NULL, public_key TEXT NOT NULL, joined_at TEXT NOT NULL, PRIMARY KEY (agent_id, swarm_id), FOREIGN KEY (swarm_id) REFERENCES swarms(swarm_id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_members_swarm ON swarm_members(swarm_id);
CREATE TABLE IF NOT EXISTS message_queue (message_id TEXT PRIMARY KEY, swarm_id TEXT NOT NULL, sender_id TEXT NOT NULL, message_type TEXT NOT NULL, content TEXT NOT NULL, received_at TEXT NOT NULL, processed_at TEXT, status TEXT NOT NULL DEFAULT 'pending', error TEXT);
CREATE INDEX IF NOT EXISTS idx_queue_status ON message_queue(status, received_at);
CREATE INDEX IF NOT EXISTS idx_queue_swarm ON message_queue(swarm_id);
CREATE TABLE IF NOT EXISTS muted_agents (agent_id TEXT PRIMARY KEY, muted_at TEXT NOT NULL, reason TEXT);
CREATE TABLE IF NOT EXISTS muted_swarms (swarm_id TEXT PRIMARY KEY, muted_at TEXT NOT NULL, reason TEXT);
CREATE TABLE IF NOT EXISTS public_keys (agent_id TEXT PRIMARY KEY, public_key TEXT NOT NULL, fetched_at TEXT NOT NULL, endpoint TEXT);
CREATE TABLE IF NOT EXISTS sdk_sessions (swarm_id TEXT NOT NULL, peer_id TEXT NOT NULL, session_id TEXT NOT NULL, last_active TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active', PRIMARY KEY (swarm_id, peer_id));
CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON sdk_sessions(last_active);
INSERT OR IGNORE INTO schema_versions (version, applied_at) VALUES ('1.0.0', datetime('now'));
"""

_INBOX_OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS inbox (
    message_id   TEXT PRIMARY KEY,
    swarm_id     TEXT NOT NULL,
    sender_id    TEXT NOT NULL,
    recipient_id TEXT,
    message_type TEXT NOT NULL,
    content      TEXT NOT NULL,
    received_at  TEXT NOT NULL,
    read_at      TEXT,
    deleted_at   TEXT,
    status       TEXT NOT NULL DEFAULT 'unread',
    CHECK(status IN ('unread', 'read', 'archived', 'deleted'))
);
CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox(status, received_at);
CREATE INDEX IF NOT EXISTS idx_inbox_swarm ON inbox(swarm_id);
CREATE INDEX IF NOT EXISTS idx_inbox_sender ON inbox(sender_id);

CREATE TABLE IF NOT EXISTS outbox (
    message_id   TEXT PRIMARY KEY,
    swarm_id     TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',
    content      TEXT NOT NULL,
    sent_at      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'sent',
    error        TEXT,
    CHECK(status IN ('sent', 'delivered', 'failed'))
);
CREATE INDEX IF NOT EXISTS idx_outbox_swarm ON outbox(swarm_id);
CREATE INDEX IF NOT EXISTS idx_outbox_sent ON outbox(sent_at);
"""

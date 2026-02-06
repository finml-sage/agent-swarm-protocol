"""Database connection and lifecycle management."""
import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

class DatabaseError(Exception): pass

class DatabaseManager:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._initialized = False
    @property
    def db_path(self) -> Path: return self._db_path
    @property
    def is_initialized(self) -> bool: return self._initialized
    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connection() as conn:
            await conn.executescript(_SCHEMA)
            await conn.commit()
        self._initialized = True
    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        conn = await aiosqlite.connect(self._db_path)
        conn.row_factory = aiosqlite.Row
        try:
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            await conn.close()
    async def close(self) -> None: self._initialized = False

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

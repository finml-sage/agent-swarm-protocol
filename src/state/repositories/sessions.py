"""SDK session repository for conversation continuity."""
import aiosqlite
from datetime import datetime, timezone
from typing import Optional

from src.state.models.session import SdkSession


class SessionRepository:
    """Persists SDK session IDs for cross-message conversation continuity.

    Each (swarm_id, peer_id) pair maps to a single session. Upserting
    replaces any previous session for the same pair.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def upsert(self, session: SdkSession) -> None:
        """Insert or replace the session for a swarm/peer pair.

        Args:
            session: The SDK session to persist.
        """
        await self._conn.execute(
            "INSERT OR REPLACE INTO sdk_sessions "
            "(swarm_id, peer_id, session_id, last_active, state) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                session.swarm_id,
                session.peer_id,
                session.session_id,
                session.last_active.isoformat(),
                session.state,
            ),
        )
        await self._conn.commit()

    async def get(
        self, swarm_id: str, peer_id: str
    ) -> Optional[SdkSession]:
        """Look up the session for a swarm/peer pair.

        Args:
            swarm_id: The swarm identifier.
            peer_id: The remote agent identifier.

        Returns:
            The SdkSession if found, None otherwise.
        """
        cursor = await self._conn.execute(
            "SELECT * FROM sdk_sessions "
            "WHERE swarm_id = ? AND peer_id = ?",
            (swarm_id, peer_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    async def get_active(
        self, swarm_id: str, peer_id: str, timeout_minutes: int
    ) -> Optional[SdkSession]:
        """Look up a non-expired session for a swarm/peer pair.

        Args:
            swarm_id: The swarm identifier.
            peer_id: The remote agent identifier.
            timeout_minutes: Maximum idle time before expiry.

        Returns:
            The SdkSession if found and not expired, None otherwise.
        """
        session = await self.get(swarm_id, peer_id)
        if session is None:
            return None
        if session.is_expired(timeout_minutes):
            await self.delete(swarm_id, peer_id)
            return None
        return session

    async def delete(self, swarm_id: str, peer_id: str) -> bool:
        """Remove a session for a swarm/peer pair.

        Returns:
            True if a session was deleted.
        """
        cursor = await self._conn.execute(
            "DELETE FROM sdk_sessions "
            "WHERE swarm_id = ? AND peer_id = ?",
            (swarm_id, peer_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def purge_expired(self, timeout_minutes: int) -> int:
        """Remove all sessions older than the timeout.

        Args:
            timeout_minutes: Maximum idle time in minutes.

        Returns:
            Number of sessions purged.
        """
        cutoff = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            "DELETE FROM sdk_sessions WHERE "
            "julianday(?) - julianday(last_active) > ?",
            (cutoff, timeout_minutes / 1440.0),
        )
        await self._conn.commit()
        return cursor.rowcount

    @staticmethod
    def _row_to_session(row: aiosqlite.Row) -> SdkSession:
        """Convert a database row to an SdkSession."""
        return SdkSession(
            swarm_id=row["swarm_id"],
            peer_id=row["peer_id"],
            session_id=row["session_id"],
            last_active=datetime.fromisoformat(row["last_active"]),
            state=row["state"],
        )

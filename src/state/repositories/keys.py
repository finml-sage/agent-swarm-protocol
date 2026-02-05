"""Public key repository."""
import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import Optional
from src.state.models.public_key import PublicKeyEntry

class PublicKeyRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None: self._conn = conn
    async def store(self, e: PublicKeyEntry) -> None:
        await self._conn.execute("INSERT OR REPLACE INTO public_keys VALUES (?, ?, ?, ?)", (e.agent_id, e.public_key, e.fetched_at.isoformat(), e.endpoint))
        await self._conn.commit()
    async def get(self, agent_id: str) -> Optional[PublicKeyEntry]:
        c = await self._conn.execute("SELECT * FROM public_keys WHERE agent_id = ?", (agent_id,))
        r = await c.fetchone()
        return PublicKeyEntry(agent_id=r["agent_id"], public_key=r["public_key"], fetched_at=datetime.fromisoformat(r["fetched_at"]), endpoint=r["endpoint"]) if r else None
    async def delete(self, agent_id: str) -> bool:
        c = await self._conn.execute("DELETE FROM public_keys WHERE agent_id = ?", (agent_id,))
        await self._conn.commit()
        return c.rowcount > 0
    async def get_all(self) -> list[PublicKeyEntry]:
        c = await self._conn.execute("SELECT * FROM public_keys")
        return [PublicKeyEntry(agent_id=r["agent_id"], public_key=r["public_key"], fetched_at=datetime.fromisoformat(r["fetched_at"]), endpoint=r["endpoint"]) for r in await c.fetchall()]
    async def get_stale(self, ttl_hours: int = 24) -> list[PublicKeyEntry]:
        c = await self._conn.execute("SELECT * FROM public_keys WHERE fetched_at < ?", ((datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat(),))
        return [PublicKeyEntry(agent_id=r["agent_id"], public_key=r["public_key"], fetched_at=datetime.fromisoformat(r["fetched_at"]), endpoint=r["endpoint"]) for r in await c.fetchall()]

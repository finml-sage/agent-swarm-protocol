"""Mute repository."""
import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from src.state.models.mute import MutedAgent, MutedSwarm

class MuteRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None: self._conn = conn
    async def mute_agent(self, agent_id: str, reason: Optional[str] = None) -> None:
        await self._conn.execute("INSERT OR REPLACE INTO muted_agents VALUES (?, ?, ?)", (agent_id, datetime.now(timezone.utc).isoformat(), reason))
        await self._conn.commit()
    async def unmute_agent(self, agent_id: str) -> bool:
        c = await self._conn.execute("DELETE FROM muted_agents WHERE agent_id = ?", (agent_id,))
        await self._conn.commit()
        return c.rowcount > 0
    async def is_agent_muted(self, agent_id: str) -> bool:
        c = await self._conn.execute("SELECT 1 FROM muted_agents WHERE agent_id = ?", (agent_id,))
        return await c.fetchone() is not None
    async def get_muted_agent(self, agent_id: str) -> Optional[MutedAgent]:
        c = await self._conn.execute("SELECT * FROM muted_agents WHERE agent_id = ?", (agent_id,))
        r = await c.fetchone()
        return MutedAgent(agent_id=r["agent_id"], muted_at=datetime.fromisoformat(r["muted_at"]), reason=r["reason"]) if r else None
    async def get_all_muted_agents(self) -> list[MutedAgent]:
        c = await self._conn.execute("SELECT * FROM muted_agents")
        return [MutedAgent(agent_id=r["agent_id"], muted_at=datetime.fromisoformat(r["muted_at"]), reason=r["reason"]) for r in await c.fetchall()]
    async def mute_swarm(self, swarm_id: str, reason: Optional[str] = None) -> None:
        await self._conn.execute("INSERT OR REPLACE INTO muted_swarms VALUES (?, ?, ?)", (swarm_id, datetime.now(timezone.utc).isoformat(), reason))
        await self._conn.commit()
    async def unmute_swarm(self, swarm_id: str) -> bool:
        c = await self._conn.execute("DELETE FROM muted_swarms WHERE swarm_id = ?", (swarm_id,))
        await self._conn.commit()
        return c.rowcount > 0
    async def is_swarm_muted(self, swarm_id: str) -> bool:
        c = await self._conn.execute("SELECT 1 FROM muted_swarms WHERE swarm_id = ?", (swarm_id,))
        return await c.fetchone() is not None
    async def get_muted_swarm(self, swarm_id: str) -> Optional[MutedSwarm]:
        c = await self._conn.execute("SELECT * FROM muted_swarms WHERE swarm_id = ?", (swarm_id,))
        r = await c.fetchone()
        return MutedSwarm(swarm_id=r["swarm_id"], muted_at=datetime.fromisoformat(r["muted_at"]), reason=r["reason"]) if r else None
    async def get_all_muted_swarms(self) -> list[MutedSwarm]:
        c = await self._conn.execute("SELECT * FROM muted_swarms")
        return [MutedSwarm(swarm_id=r["swarm_id"], muted_at=datetime.fromisoformat(r["muted_at"]), reason=r["reason"]) for r in await c.fetchall()]

"""Membership repository."""
import aiosqlite
from datetime import datetime
from typing import Optional
from src.state.models.member import SwarmMember, SwarmSettings, SwarmMembership

class MembershipRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None: self._conn = conn
    async def create_swarm(self, m: SwarmMembership) -> None:
        await self._conn.execute("INSERT INTO swarms VALUES (?, ?, ?, ?, ?, ?)", (m.swarm_id, m.name, m.master, m.joined_at.isoformat(), int(m.settings.allow_member_invite), int(m.settings.require_approval)))
        for member in m.members: await self._conn.execute("INSERT INTO swarm_members VALUES (?, ?, ?, ?, ?)", (member.agent_id, m.swarm_id, member.endpoint, member.public_key, member.joined_at.isoformat()))
        await self._conn.commit()
    async def add_member(self, swarm_id: str, m: SwarmMember) -> None:
        await self._conn.execute("INSERT INTO swarm_members VALUES (?, ?, ?, ?, ?)", (m.agent_id, swarm_id, m.endpoint, m.public_key, m.joined_at.isoformat()))
        await self._conn.commit()
    async def remove_member(self, swarm_id: str, agent_id: str) -> bool:
        c = await self._conn.execute("DELETE FROM swarm_members WHERE swarm_id = ? AND agent_id = ?", (swarm_id, agent_id))
        await self._conn.commit()
        return c.rowcount > 0
    async def get_swarm(self, swarm_id: str) -> Optional[SwarmMembership]:
        c = await self._conn.execute("SELECT * FROM swarms WHERE swarm_id = ?", (swarm_id,))
        r = await c.fetchone()
        if not r: return None
        mc = await self._conn.execute("SELECT * FROM swarm_members WHERE swarm_id = ?", (swarm_id,))
        members = tuple(SwarmMember(agent_id=m["agent_id"], endpoint=m["endpoint"], public_key=m["public_key"], joined_at=datetime.fromisoformat(m["joined_at"])) for m in await mc.fetchall())
        return SwarmMembership(swarm_id=r["swarm_id"], name=r["name"], master=r["master"], members=members, joined_at=datetime.fromisoformat(r["joined_at"]), settings=SwarmSettings(allow_member_invite=bool(r["allow_member_invite"]), require_approval=bool(r["require_approval"])))
    async def get_all_swarms(self) -> list[SwarmMembership]:
        c = await self._conn.execute("SELECT swarm_id FROM swarms")
        return [await self.get_swarm(r[0]) for r in await c.fetchall()]
    async def delete_swarm(self, swarm_id: str) -> bool:
        c = await self._conn.execute("DELETE FROM swarms WHERE swarm_id = ?", (swarm_id,))
        await self._conn.commit()
        return c.rowcount > 0

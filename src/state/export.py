"""State export and import."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from src.state.database import DatabaseManager
from src.state.repositories.membership import MembershipRepository
from src.state.repositories.mutes import MuteRepository
from src.state.repositories.keys import PublicKeyRepository

class StateImportError(Exception): pass

async def export_state(db: DatabaseManager, agent_id: str) -> dict[str, Any]:
    async with db.connection() as conn:
        swarms = await MembershipRepository(conn).get_all_swarms()
        muted_agents = await MuteRepository(conn).get_all_muted_agents()
        muted_swarms = await MuteRepository(conn).get_all_muted_swarms()
        public_keys = await PublicKeyRepository(conn).get_all()
    return {"schema_version": "1.0.0", "agent_id": agent_id, "exported_at": datetime.now(timezone.utc).isoformat(),
            "swarms": {s.swarm_id: {"swarm_id": s.swarm_id, "name": s.name, "master": s.master, "members": [{"agent_id": m.agent_id, "endpoint": m.endpoint, "public_key": m.public_key, "joined_at": m.joined_at.isoformat()} for m in s.members], "joined_at": s.joined_at.isoformat(), "settings": {"allow_member_invite": s.settings.allow_member_invite, "require_approval": s.settings.require_approval}} for s in swarms},
            "muted_swarms": [m.swarm_id for m in muted_swarms], "muted_agents": [m.agent_id for m in muted_agents],
            "public_keys": {k.agent_id: {"public_key": k.public_key, "fetched_at": k.fetched_at.isoformat(), **({"endpoint": k.endpoint} if k.endpoint else {})} for k in public_keys}}

async def export_state_to_file(db: DatabaseManager, agent_id: str, path: Path) -> None:
    state = await export_state(db, agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: json.dump(state, f, indent=2)

async def import_state(db: DatabaseManager, state: dict[str, Any], merge: bool = False) -> None:
    if state.get("schema_version") != "1.0.0": raise StateImportError(f"Unsupported schema version: {state.get('schema_version')}")
    async with db.connection() as conn:
        if not merge:
            for tbl in ["swarm_members", "swarms", "muted_agents", "muted_swarms", "public_keys"]: await conn.execute(f"DELETE FROM {tbl}")
            await conn.commit()
        now = datetime.now(timezone.utc).isoformat()
        for sid, s in state.get("swarms", {}).items():
            settings = s.get("settings", {})
            await conn.execute("INSERT OR REPLACE INTO swarms VALUES (?, ?, ?, ?, ?, ?)", (sid, s["name"], s["master"], s["joined_at"], int(settings.get("allow_member_invite", False)), int(settings.get("require_approval", False))))
            for m in s.get("members", []): await conn.execute("INSERT OR REPLACE INTO swarm_members VALUES (?, ?, ?, ?, ?)", (m["agent_id"], sid, m["endpoint"], m["public_key"], m["joined_at"]))
        for sid in state.get("muted_swarms", []): await conn.execute("INSERT OR IGNORE INTO muted_swarms (swarm_id, muted_at) VALUES (?, ?)", (sid, now))
        for aid in state.get("muted_agents", []): await conn.execute("INSERT OR IGNORE INTO muted_agents (agent_id, muted_at) VALUES (?, ?)", (aid, now))
        for aid, e in state.get("public_keys", {}).items(): await conn.execute("INSERT OR REPLACE INTO public_keys VALUES (?, ?, ?, ?)", (aid, e["public_key"], e["fetched_at"], e.get("endpoint")))
        await conn.commit()

async def import_state_from_file(db: DatabaseManager, path: Path, merge: bool = False) -> None:
    if not path.exists(): raise StateImportError(f"File not found: {path}")
    with open(path, "r", encoding="utf-8") as f: state = json.load(f)
    await import_state(db, state, merge)

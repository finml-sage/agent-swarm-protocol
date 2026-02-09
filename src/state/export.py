"""State export and import."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from src.state.database import DatabaseManager
from src.state.repositories.membership import MembershipRepository
from src.state.repositories.mutes import MuteRepository
from src.state.repositories.keys import PublicKeyRepository
from src.state.repositories.inbox import InboxRepository
from src.state.repositories.outbox import OutboxRepository
from src.state.models.inbox import InboxMessage, InboxStatus

_CURRENT_SCHEMA_VERSION = "2.0.0"
_SUPPORTED_IMPORT_VERSIONS = {"1.0.0", "2.0.0"}


class StateImportError(Exception): pass


async def export_state(db: DatabaseManager, agent_id: str) -> dict[str, Any]:
    async with db.connection() as conn:
        swarms = await MembershipRepository(conn).get_all_swarms()
        muted_agents = await MuteRepository(conn).get_all_muted_agents()
        muted_swarms = await MuteRepository(conn).get_all_muted_swarms()
        public_keys = await PublicKeyRepository(conn).get_all()
        # Export inbox (non-deleted)
        inbox_repo = InboxRepository(conn)
        inbox_msgs = await inbox_repo.list_visible("all", limit=100)
        # Export outbox
        outbox_repo = OutboxRepository(conn)
        outbox_msgs = await outbox_repo.list_all(limit=100)
    return {
        "schema_version": _CURRENT_SCHEMA_VERSION,
        "agent_id": agent_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "swarms": {
            s.swarm_id: {
                "swarm_id": s.swarm_id, "name": s.name, "master": s.master,
                "members": [
                    {"agent_id": m.agent_id, "endpoint": m.endpoint,
                     "public_key": m.public_key, "joined_at": m.joined_at.isoformat()}
                    for m in s.members
                ],
                "joined_at": s.joined_at.isoformat(),
                "settings": {
                    "allow_member_invite": s.settings.allow_member_invite,
                    "require_approval": s.settings.require_approval,
                },
            }
            for s in swarms
        },
        "muted_swarms": [m.swarm_id for m in muted_swarms],
        "muted_agents": [m.agent_id for m in muted_agents],
        "public_keys": {
            k.agent_id: {
                "public_key": k.public_key,
                "fetched_at": k.fetched_at.isoformat(),
                **({"endpoint": k.endpoint} if k.endpoint else {}),
            }
            for k in public_keys
        },
        "inbox": [
            {
                "message_id": m.message_id, "swarm_id": m.swarm_id,
                "sender_id": m.sender_id, "recipient_id": m.recipient_id,
                "message_type": m.message_type, "content": m.content,
                "received_at": m.received_at.isoformat(),
                "status": m.status.value,
                "read_at": m.read_at.isoformat() if m.read_at else None,
                "deleted_at": m.deleted_at.isoformat() if m.deleted_at else None,
            }
            for m in inbox_msgs
        ],
        "outbox": [
            {
                "message_id": m.message_id, "swarm_id": m.swarm_id,
                "recipient_id": m.recipient_id, "message_type": m.message_type,
                "content": m.content, "sent_at": m.sent_at.isoformat(),
                "status": m.status.value,
                "delivered_at": m.delivered_at.isoformat() if m.delivered_at else None,
                "error": m.error,
            }
            for m in outbox_msgs
        ],
    }


async def export_state_to_file(db: DatabaseManager, agent_id: str, path: Path) -> None:
    state = await export_state(db, agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: json.dump(state, f, indent=2)


async def import_state(db: DatabaseManager, state: dict[str, Any], merge: bool = False) -> None:
    version = state.get("schema_version", "")
    if version not in _SUPPORTED_IMPORT_VERSIONS:
        raise StateImportError(f"Unsupported schema version: {version}")
    async with db.connection() as conn:
        if not merge:
            for tbl in ["swarm_members", "swarms", "muted_agents", "muted_swarms", "public_keys", "inbox", "outbox"]:
                await conn.execute(f"DELETE FROM {tbl}")
            await conn.commit()
        now = datetime.now(timezone.utc).isoformat()
        # Import swarms, mutes, keys (same for both versions)
        for sid, s in state.get("swarms", {}).items():
            settings = s.get("settings", {})
            await conn.execute("INSERT OR REPLACE INTO swarms VALUES (?, ?, ?, ?, ?, ?)", (sid, s["name"], s["master"], s["joined_at"], int(settings.get("allow_member_invite", False)), int(settings.get("require_approval", False))))
            for m in s.get("members", []): await conn.execute("INSERT OR REPLACE INTO swarm_members VALUES (?, ?, ?, ?, ?)", (m["agent_id"], sid, m["endpoint"], m["public_key"], m["joined_at"]))
        for sid in state.get("muted_swarms", []): await conn.execute("INSERT OR IGNORE INTO muted_swarms (swarm_id, muted_at) VALUES (?, ?)", (sid, now))
        for aid in state.get("muted_agents", []): await conn.execute("INSERT OR IGNORE INTO muted_agents (agent_id, muted_at) VALUES (?, ?)", (aid, now))
        for aid, e in state.get("public_keys", {}).items(): await conn.execute("INSERT OR REPLACE INTO public_keys VALUES (?, ?, ?, ?)", (aid, e["public_key"], e["fetched_at"], e.get("endpoint")))
        # Import inbox
        if version == "2.0.0":
            for m in state.get("inbox", []):
                await conn.execute(
                    "INSERT OR REPLACE INTO inbox (message_id, swarm_id, sender_id, recipient_id, message_type, content, received_at, read_at, deleted_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (m["message_id"], m["swarm_id"], m["sender_id"], m.get("recipient_id"), m["message_type"], m["content"], m["received_at"], m.get("read_at"), m.get("deleted_at"), m["status"]),
                )
            for m in state.get("outbox", []):
                await conn.execute(
                    "INSERT OR REPLACE INTO outbox (message_id, swarm_id, recipient_id, message_type, content, sent_at, delivered_at, status, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (m["message_id"], m["swarm_id"], m["recipient_id"], m["message_type"], m["content"], m["sent_at"], m.get("delivered_at"), m["status"], m.get("error")),
                )
        elif version == "1.0.0":
            # Legacy: import message_queue data into inbox
            for m in state.get("message_queue", []):
                old_status = m.get("status", "pending")
                inbox_status = "unread" if old_status in ("pending", "processing") else "read"
                await conn.execute(
                    "INSERT OR REPLACE INTO inbox (message_id, swarm_id, sender_id, recipient_id, message_type, content, received_at, read_at, deleted_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (m["message_id"], m["swarm_id"], m["sender_id"], None, m["message_type"], m["content"], m["received_at"], m.get("processed_at"), None, inbox_status),
                )
        await conn.commit()


async def import_state_from_file(db: DatabaseManager, path: Path, merge: bool = False) -> None:
    if not path.exists(): raise StateImportError(f"File not found: {path}")
    with open(path, "r", encoding="utf-8") as f: state = json.load(f)
    await import_state(db, state, merge)

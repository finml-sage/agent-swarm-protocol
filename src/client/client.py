"""Main SwarmClient class for agent-to-agent communication."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .builder import MessageBuilder
from .crypto import public_key_to_base64, sign_message
from .exceptions import NotMasterError, NotMemberError
from .message import Message
from .messaging import broadcast_message, send_to_recipient
from .operations import create_swarm, join_swarm, kick_member, leave_swarm
from .persist import save_swarm_membership
from .tokens import generate_invite_token
from .transport import Transport
from .types import MessageType, Priority, SwarmMembership

if TYPE_CHECKING:
    from src.state.database import DatabaseManager


class SwarmClient:
    """Client for Agent Swarm Protocol. Must be used as async context manager."""

    def __init__(self, agent_id: str, endpoint: str, private_key: Ed25519PrivateKey,
                 timeout: float = 30.0, max_retries: int = 3,
                 db: DatabaseManager | None = None) -> None:
        self._agent_id = agent_id
        self._endpoint = endpoint
        self._private_key = private_key
        self._public_key_b64 = public_key_to_base64(private_key.public_key())
        self._transport = Transport(agent_id, timeout, max_retries)
        self._swarms: dict[str, SwarmMembership] = {}
        self._db = db

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def public_key_base64(self) -> str:
        return self._public_key_b64

    async def __aenter__(self) -> "SwarmClient":
        await self._transport.__aenter__()
        return self

    async def __aexit__(self, *args) -> None:
        await self._transport.__aexit__(*args)

    async def send_message(self, swarm_id: UUID, content: str, recipient: str = "broadcast",
                           message_type: MessageType = MessageType.MESSAGE, priority: Priority = Priority.NORMAL,
                           in_reply_to: UUID | None = None, thread_id: UUID | None = None,
                           expires_at: datetime | None = None, metadata: dict | None = None) -> Message:
        swarm = self._get_swarm(swarm_id)
        b = MessageBuilder(self._agent_id, self._endpoint).in_swarm(swarm_id).to(recipient).with_content(content).as_type(message_type).with_priority(priority)
        if in_reply_to:
            b.replying_to(in_reply_to)
        if thread_id:
            b.in_thread(thread_id)
        if expires_at:
            b.expires(expires_at)
        for k, v in (metadata or {}).items():
            b.with_metadata(k, v)
        msg = b.build()
        sd = msg.to_signing_dict()
        msg.signature = sign_message(self._private_key, sd["message_id"], sd["timestamp"], sd["swarm_id"], sd["recipient"], sd["type"], sd["content"])
        wire = msg.to_wire_format()
        await (broadcast_message(self._transport, swarm, self._agent_id, wire) if recipient == "broadcast" else send_to_recipient(self._transport, swarm, recipient, wire))
        return msg

    async def create_swarm(self, name: str, allow_member_invite: bool = False, require_approval: bool = False) -> SwarmMembership:
        """Create a new swarm and persist it to the local database if configured."""
        m = create_swarm(name, self._agent_id, self._endpoint, self._public_key_b64, allow_member_invite, require_approval)
        self._swarms[m["swarm_id"]] = m
        if self._db is not None:
            await save_swarm_membership(self._db, m)
        return m

    def generate_invite(self, swarm_id: UUID, expires_at: datetime | None = None, max_uses: int | None = None) -> str:
        s = self._get_swarm(swarm_id)
        if s["master"] != self._agent_id and not s["settings"]["allow_member_invite"]:
            raise NotMasterError(f"Only master can invite to {swarm_id}")
        ep = self._endpoint if s["master"] == self._agent_id else next(m["endpoint"] for m in s["members"] if m["agent_id"] == s["master"])
        return generate_invite_token(self._private_key, swarm_id, s["master"], ep, expires_at, max_uses)

    async def join_swarm(self, invite_token_url: str) -> SwarmMembership:
        """Join a swarm via invite token and persist membership to local database."""
        m = await join_swarm(self._transport, invite_token_url, self._agent_id, self._endpoint, self._private_key)
        self._swarms[m["swarm_id"]] = m
        if self._db is not None:
            await save_swarm_membership(self._db, m)
        return m

    async def leave_swarm(self, swarm_id: UUID) -> None:
        await leave_swarm(self._transport, self._get_swarm(swarm_id), self._agent_id, self._endpoint, self._private_key)
        del self._swarms[str(swarm_id)]

    async def kick_member(self, swarm_id: UUID, target: str, reason: str | None = None) -> None:
        s = self._get_swarm(swarm_id)
        await kick_member(self._transport, s, self._agent_id, self._endpoint, self._private_key, target, reason)
        s["members"] = [m for m in s["members"] if m["agent_id"] != target]

    def get_swarm(self, swarm_id: UUID) -> SwarmMembership | None:
        return self._swarms.get(str(swarm_id))

    def list_swarms(self) -> list[SwarmMembership]:
        return list(self._swarms.values())

    def add_swarm(self, membership: SwarmMembership) -> None:
        self._swarms[membership["swarm_id"]] = membership

    def _get_swarm(self, swarm_id: UUID) -> SwarmMembership:
        s = self._swarms.get(str(swarm_id))
        if not s:
            raise NotMemberError(f"Not a member of {swarm_id}")
        return s

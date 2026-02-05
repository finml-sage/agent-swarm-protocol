"""Swarm operations: create, join, leave, kick."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .crypto import public_key_to_base64, sign_message
from .exceptions import NotMasterError, NotMemberError, SwarmError, TokenError, TransportError
from .tokens import parse_invite_token
from .transport import Transport
from .types import SwarmMember, SwarmMembership, SwarmSettings


def create_swarm(name: str, master_id: str, master_endpoint: str, master_pk_b64: str,
                 allow_member_invite: bool = False, require_approval: bool = False) -> SwarmMembership:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return SwarmMembership(swarm_id=str(uuid4()), name=name, master=master_id,
        members=[SwarmMember(agent_id=master_id, endpoint=master_endpoint, public_key=master_pk_b64, joined_at=now)],
        joined_at=now, settings=SwarmSettings(allow_member_invite=allow_member_invite, require_approval=require_approval))


async def join_swarm(transport: Transport, token_url: str, agent_id: str, endpoint: str, pk: Ed25519PrivateKey) -> SwarmMembership:
    tok = parse_invite_token(token_url)
    pk_b64 = public_key_to_base64(pk.public_key())
    body = {"type": "system", "action": "join_request", "invite_token": token_url.split("?token=")[1],
            "sender": {"agent_id": agent_id, "endpoint": endpoint, "public_key": pk_b64}}
    status, resp = await transport.post(f"{tok['endpoint'].rstrip('/')}/swarm/join", body)
    if status == 202:
        raise SwarmError("Join pending approval")
    if status == 400:
        raise TokenError(f"Invalid token: {resp.get('error', {}).get('message', resp) if resp else 'Unknown'}")
    if status != 200 or not resp:
        raise TransportError(f"Join failed: {resp.get('error', {}).get('message', resp) if resp else 'Unknown'}", status)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    members = [SwarmMember(agent_id=m["agent_id"], endpoint=m["endpoint"], public_key=m["public_key"], joined_at=now) for m in resp.get("members", [])]
    members.append(SwarmMember(agent_id=agent_id, endpoint=endpoint, public_key=pk_b64, joined_at=now))
    return SwarmMembership(swarm_id=tok["swarm_id"], name=resp.get("swarm_name", ""), master=tok["master"],
        members=members, joined_at=now, settings=SwarmSettings(allow_member_invite=False, require_approval=False))


async def leave_swarm(transport: Transport, swarm: SwarmMembership, agent_id: str, endpoint: str, pk: Ed25519PrivateKey) -> None:
    if not any(m["agent_id"] == agent_id for m in swarm["members"]):
        raise NotMemberError(f"Not a member of {swarm['swarm_id']}")
    now = datetime.now(timezone.utc)
    mid, sid = uuid4(), UUID(swarm["swarm_id"])
    content = f'{{"action":"member_left","agent_id":"{agent_id}"}}'
    msg = _sys_msg(mid, now, agent_id, endpoint, "broadcast", sid, content, sign_message(pk, mid, now, sid, "broadcast", "system", content))
    for m in swarm["members"]:
        if m["agent_id"] != agent_id:
            try:
                await transport.post(f"{m['endpoint'].rstrip('/')}/swarm/message", msg, retry=False)
            except TransportError:
                pass


async def kick_member(transport: Transport, swarm: SwarmMembership, master_id: str, master_ep: str, pk: Ed25519PrivateKey, target: str, reason: str | None = None) -> None:
    if swarm["master"] != master_id:
        raise NotMasterError("Only master can kick")
    t = next((m for m in swarm["members"] if m["agent_id"] == target), None)
    if not t:
        raise NotMemberError(f"{target} not in swarm")
    now, sid = datetime.now(timezone.utc), UUID(swarm["swarm_id"])
    kick_c = f'{{"action":"kicked","agent_id":"{target}"' + (f',"reason":"{reason}"}}' if reason else "}")
    mid1 = uuid4()
    await transport.post(f"{t['endpoint'].rstrip('/')}/swarm/message", _sys_msg(mid1, now, master_id, master_ep, target, sid, kick_c, sign_message(pk, mid1, now, sid, target, "system", kick_c)))
    bc_c = f'{{"action":"member_kicked","agent_id":"{target}"' + (f',"reason":"{reason}"}}' if reason else "}")
    mid2 = uuid4()
    bc_msg = _sys_msg(mid2, now, master_id, master_ep, "broadcast", sid, bc_c, sign_message(pk, mid2, now, sid, "broadcast", "system", bc_c))
    for m in swarm["members"]:
        if m["agent_id"] not in (master_id, target):
            try:
                await transport.post(f"{m['endpoint'].rstrip('/')}/swarm/message", bc_msg, retry=False)
            except TransportError:
                pass


def _sys_msg(mid: UUID, ts: datetime, sender: str, ep: str, rcpt: str, sid: UUID, content: str, sig: str) -> dict:
    return {"protocol_version": "0.1.0", "message_id": str(mid), "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "sender": {"agent_id": sender, "endpoint": ep}, "recipient": rcpt, "swarm_id": str(sid), "type": "system", "content": content, "signature": sig}

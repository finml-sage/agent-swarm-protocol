"""Master-side cross-host broadcast for membership lifecycle events.

When the master accepts a new join (issue #200), every existing member
must receive a ``type=system, action=member_joined`` event so the
receiver-side dispatcher (PR #198) can write the new agent into their
local ``swarm_members`` table.

This module owns the fan-out: build a signed wire envelope using the
master's Ed25519 private key, then POST to each existing member's
``/swarm/message`` endpoint. Symmetric with the existing client-library
patterns in ``src/client/operations.py::leave_swarm`` and
``kick_member``, which iterate members and POST directly.

Fire-and-forget by design: a transient delivery failure to one member
must NOT fail the join itself. Each per-member POST is wrapped in its
own try/except. The caller wraps the whole call again as belt-and-
suspenders so a master-side broadcast outage never blocks the join.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.client._constants import PROTOCOL_VERSION
from src.client.crypto import sign_message
from src.state.models.member import SwarmMember

logger = logging.getLogger(__name__)

_BROADCAST_TIMEOUT_SECONDS = 5.0


def _format_timestamp(ts: datetime) -> str:
    """Match the client-side wire timestamp format (millisecond ISO + Z)."""
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_broadcast_envelope(
    *,
    swarm_id: str,
    master_id: str,
    master_endpoint: str,
    master_private_key: Ed25519PrivateKey,
    new_agent_id: str,
    new_agent_endpoint: str,
    joined_at: datetime,
    new_agent_public_key: Optional[str] = None,
) -> dict:
    """Build a signed wire envelope for a master-side member_joined broadcast.

    Returns a dict shaped like ``MessageRequest`` (see
    ``src/server/models/requests.py``):

    - ``type=system`` (real system event, NOT ``type=message`` wrapping
      system content — receiver dispatcher only fires on real system).
    - ``content`` is a JSON string carrying the lifecycle payload with
      ``endpoint``, ``joined_at`` and ``public_key`` populated (#199,
      #214 — required for the receiver to write all 5 NOT NULL
      ``swarm_members`` columns directly from the broadcast, with no
      network fetch of the new member's ``/swarm/info`` required).
    - ``signature`` signs the master's authority over the broadcast with
      the same canonical payload as ``client/operations.py``.

    ``new_agent_public_key`` is optional only for backward compatibility
    with callers that have not yet been updated; in production, callers
    sourced from ``routes/join.py`` always pass it through. When omitted,
    receivers running a post-#214 build will fall back to the legacy
    ``/swarm/info`` fetch path.
    """
    message_id = uuid.uuid4()
    swarm_uuid = uuid.UUID(swarm_id)
    joined_at_iso = _format_timestamp(joined_at)
    now = datetime.now(timezone.utc)

    content_payload: dict = {
        "type": "system",
        "action": "member_joined",
        "swarm_id": swarm_id,
        "agent_id": new_agent_id,
        "endpoint": new_agent_endpoint,
        "joined_at": joined_at_iso,
    }
    if new_agent_public_key is not None:
        content_payload["public_key"] = new_agent_public_key
    content = json.dumps(content_payload)

    signature = sign_message(
        master_private_key, message_id, now, swarm_uuid,
        "broadcast", "system", content,
    )

    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": str(message_id),
        "timestamp": _format_timestamp(now),
        "sender": {"agent_id": master_id, "endpoint": master_endpoint},
        "recipient": "broadcast",
        "swarm_id": swarm_id,
        "type": "system",
        "content": content,
        "signature": signature,
    }


async def broadcast_member_joined(
    *,
    members: Iterable[SwarmMember],
    new_agent_id: str,
    swarm_id: str,
    master_id: str,
    master_endpoint: str,
    master_private_key: Ed25519PrivateKey,
    new_agent_endpoint: str,
    joined_at: datetime,
    new_agent_public_key: Optional[str] = None,
) -> tuple[int, int]:
    """Fan out the member_joined broadcast to every existing member.

    Per-member failures are logged and swallowed: the broadcast is
    best-effort delivery, NOT atomic. When the broadcast carries the new
    member's ``public_key`` inline (#214), receivers can populate
    ``swarm_members`` directly with no network call. If the broadcast
    omits ``public_key`` (legacy masters), receivers fall back to a
    ``/swarm/info`` fetch — which is the brittle path that issue #214
    was filed against.

    Returns ``(delivered, attempted)`` for caller-side observability.
    The new joiner and the master itself are skipped (they already have
    state).
    """
    envelope = build_broadcast_envelope(
        swarm_id=swarm_id,
        master_id=master_id,
        master_endpoint=master_endpoint,
        master_private_key=master_private_key,
        new_agent_id=new_agent_id,
        new_agent_endpoint=new_agent_endpoint,
        joined_at=joined_at,
        new_agent_public_key=new_agent_public_key,
    )

    targets = [
        m for m in members
        if m.agent_id != new_agent_id and m.agent_id != master_id
    ]
    if not targets:
        logger.info(
            "member_joined broadcast for '%s' in swarm '%s': no other members",
            new_agent_id, swarm_id,
        )
        return (0, 0)

    delivered = 0
    async with httpx.AsyncClient(timeout=_BROADCAST_TIMEOUT_SECONDS) as client:
        for target in targets:
            url = f"{target.endpoint.rstrip('/')}/message"
            try:
                response = await client.post(url, json=envelope)
            except httpx.HTTPError as exc:
                logger.warning(
                    "member_joined broadcast to '%s' at %s failed: %s",
                    target.agent_id, url, exc,
                )
                continue
            if response.status_code not in (200, 202):
                logger.warning(
                    "member_joined broadcast to '%s' returned %s",
                    target.agent_id, response.status_code,
                )
                continue
            delivered += 1

    logger.info(
        "member_joined broadcast for '%s' in swarm '%s': delivered=%d/%d",
        new_agent_id, swarm_id, delivered, len(targets),
    )
    return (delivered, len(targets))

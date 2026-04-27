"""Receiver-side dispatch for system membership lifecycle events.

When a member receives a system message with action=member_joined, member_left,
or member_kicked, the local swarm_members table must be updated so direct A2A
sends can route. Without this dispatch, members can only reach a newly-joined
agent via broadcast — direct sends fail silently on the sender side.

Path 1b from issue #197: lazy-fetch /swarm/info on the new member's endpoint
to retrieve the public_key, pull swarm_id from the message envelope, and
INSERT OR IGNORE into swarm_members. INSERT OR REPLACE into public_keys to
pre-warm the verification cache. Symmetric DELETE for member_left/member_kicked
on swarm_members only — public_keys cache survives churn.

Network failures fetching /swarm/info are logged and swallowed: the message
must remain accepted, and the lazy-fetch fallback in the signature verifier
will populate public_keys on first inbound message from the new member.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from src.server.models.requests import MessageRequest
from src.state.database import DatabaseManager
from src.state.models.public_key import PublicKeyEntry
from src.state.repositories.keys import PublicKeyRepository

logger = logging.getLogger(__name__)


# These actions are the receiver-side membership lifecycle events that
# mutate local swarm_members state. Mute/unmute do not change membership
# and are deliberately excluded.
_JOIN_ACTION = "member_joined"
_LEAVE_ACTIONS = {"member_left", "member_kicked"}

_SWARM_INFO_TIMEOUT_SECONDS = 5.0
_PROTOCOL_VERSION = "0.1.0"


def _parse_action(content: str) -> Optional[dict[str, Any]]:
    """Return parsed action dict from JSON content, or None on bad input.

    System lifecycle messages carry a JSON object as content with at least
    an `action` field. Returns None for non-JSON content or content that
    is not a JSON object — those are not lifecycle events.
    """
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


async def _fetch_public_key(
    endpoint: str, agent_id: str, local_agent_id: str,
) -> Optional[str]:
    """GET <endpoint>/info and return base64 public_key, or None.

    Endpoint convention: the swarm member's endpoint already includes the
    /swarm prefix (e.g. https://host/swarm), and routes are appended as
    bare names. Mirrors the join URL pattern in src/client/operations.py
    (`{endpoint.rstrip('/')}/join`).

    Failures (timeout, non-200, missing field, mismatched agent_id) log and
    return None. The caller continues without the public_key — the lazy-fetch
    fallback in the signature verifier will populate the cache later.
    """
    url = f"{endpoint.rstrip('/')}/info"
    headers = {
        "X-Agent-ID": local_agent_id,
        "X-Swarm-Protocol": _PROTOCOL_VERSION,
    }
    try:
        async with httpx.AsyncClient(
            timeout=_SWARM_INFO_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning(
            "Failed to fetch /swarm/info for new member '%s' at %s: %s",
            agent_id, endpoint, exc,
        )
        return None
    if response.status_code != 200:
        logger.warning(
            "/swarm/info for new member '%s' returned %s",
            agent_id, response.status_code,
        )
        return None
    try:
        data = response.json()
    except ValueError:
        logger.warning(
            "/swarm/info for new member '%s' returned non-JSON body",
            agent_id,
        )
        return None
    if not isinstance(data, dict):
        logger.warning(
            "/swarm/info for new member '%s' returned non-object body",
            agent_id,
        )
        return None
    public_key = data.get("public_key")
    info_agent_id = data.get("agent_id")
    if not isinstance(public_key, str) or not public_key:
        logger.warning(
            "/swarm/info for '%s' missing or invalid public_key field",
            agent_id,
        )
        return None
    if info_agent_id != agent_id:
        logger.warning(
            "/swarm/info agent_id mismatch: expected '%s', got '%s'",
            agent_id, info_agent_id,
        )
        return None
    return public_key


async def _handle_member_joined(
    db: DatabaseManager,
    swarm_id: str,
    new_agent_id: str,
    new_endpoint: str,
    joined_at_iso: str,
    public_key: str,
) -> None:
    """Insert the new member into swarm_members and pre-warm public_keys.

    Idempotent on swarm_members (INSERT OR IGNORE — duplicate broadcasts do
    not raise and do not clobber existing rows). Pre-warms public_keys with
    INSERT OR REPLACE — the cache survives churn but the freshest copy wins.
    """
    async with db.connection() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO swarm_members "
            "(agent_id, swarm_id, endpoint, public_key, joined_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_agent_id, swarm_id, new_endpoint, public_key, joined_at_iso),
        )
        await conn.commit()
        # Pre-warm the public_keys cache via the repository so the
        # PublicKeyEntry validation runs (HTTPS endpoint check, non-empty
        # key check) before the row lands.
        entry = PublicKeyEntry(
            agent_id=new_agent_id,
            public_key=public_key,
            fetched_at=datetime.now(timezone.utc),
            endpoint=new_endpoint,
        )
        await PublicKeyRepository(conn).store(entry)
    logger.info(
        "Receiver-side sync: added '%s' to swarm_members for swarm '%s'",
        new_agent_id, swarm_id,
    )


async def _handle_member_removed(
    db: DatabaseManager,
    swarm_id: str,
    removed_agent_id: str,
    action: str,
) -> None:
    """Remove the agent from swarm_members. public_keys cache survives.

    DELETE only from swarm_members — the public_keys cache is preserved
    so signature verification of any in-flight messages from the removed
    agent still works, and a re-join does not require a re-fetch.
    """
    async with db.connection() as conn:
        cursor = await conn.execute(
            "DELETE FROM swarm_members WHERE agent_id = ? AND swarm_id = ?",
            (removed_agent_id, swarm_id),
        )
        await conn.commit()
    logger.info(
        "Receiver-side sync: removed '%s' from swarm_members for swarm "
        "'%s' on action '%s' (rows=%d)",
        removed_agent_id, swarm_id, action, cursor.rowcount,
    )


async def dispatch_system_message(
    db: DatabaseManager,
    body: MessageRequest,
    local_agent_id: str,
) -> None:
    """Apply receiver-side state mutations for membership lifecycle events.

    Called after the inbox persistence step in the message receive flow.
    Returns silently for non-system messages, non-membership-lifecycle
    actions, malformed content, or any internal error — the message must
    still be accepted regardless of dispatch outcome.

    Args:
        db: Initialized DatabaseManager.
        body: The validated MessageRequest just persisted to the inbox.
        local_agent_id: The receiving agent's own ID, used in the
            X-Agent-ID header on the /swarm/info fetch.
    """
    if body.type != "system":
        return
    payload = _parse_action(body.content)
    if payload is None:
        return
    action = payload.get("action")
    if action != _JOIN_ACTION and action not in _LEAVE_ACTIONS:
        return

    target_agent_id = payload.get("agent_id")
    if not isinstance(target_agent_id, str) or not target_agent_id:
        logger.warning(
            "System message action '%s' missing agent_id; skipping dispatch",
            action,
        )
        return

    swarm_id = body.swarm_id

    try:
        if action == _JOIN_ACTION:
            new_endpoint = payload.get("endpoint")
            if not isinstance(new_endpoint, str) or not new_endpoint:
                # The current broadcast payload (built by
                # build_notification_message in src/server/notifications.py)
                # does not include endpoint — fall back to the sender's
                # endpoint from the envelope, which carries the joining
                # agent's endpoint when the master forwards the broadcast.
                new_endpoint = body.sender.endpoint
            if not new_endpoint.startswith("https://"):
                logger.warning(
                    "member_joined for '%s': endpoint '%s' is not HTTPS; "
                    "skipping dispatch",
                    target_agent_id, new_endpoint,
                )
                return

            joined_at_iso = payload.get("joined_at")
            if not isinstance(joined_at_iso, str) or not joined_at_iso:
                # Fall back to the message timestamp if joined_at is not
                # in the payload. The current notifications.py omits
                # joined_at — the message envelope timestamp is a safe
                # proxy for "when the receiver became aware of the join".
                joined_at_iso = body.timestamp

            public_key = await _fetch_public_key(
                new_endpoint, target_agent_id, local_agent_id,
            )
            if public_key is None:
                # Fail loud (logged), continue silently. The lazy-fetch
                # in the signature verifier will populate public_keys on
                # the first inbound message from the new member, and a
                # subsequent member_joined retry — or a manual swarm
                # refresh — can complete the swarm_members write later.
                logger.warning(
                    "Skipping swarm_members insert for '%s': public_key "
                    "fetch failed; lazy-fetch will retry on first verify",
                    target_agent_id,
                )
                return

            await _handle_member_joined(
                db=db,
                swarm_id=swarm_id,
                new_agent_id=target_agent_id,
                new_endpoint=new_endpoint,
                joined_at_iso=joined_at_iso,
                public_key=public_key,
            )
        else:
            await _handle_member_removed(
                db=db,
                swarm_id=swarm_id,
                removed_agent_id=target_agent_id,
                action=action,
            )
    except Exception as exc:
        # Last-resort guard: a dispatch failure must never block message
        # acceptance. Log loudly so the gap is visible to operators.
        logger.exception(
            "Receiver-side dispatch failed for action '%s' agent '%s' "
            "swarm '%s': %s",
            action, target_agent_id, swarm_id, exc,
        )

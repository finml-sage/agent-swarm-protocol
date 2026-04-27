"""Tests for master-side member_joined broadcast (issue #200).

When a new agent joins via /swarm/join, the master must broadcast a
`type=system, action=member_joined` event to every existing member so
PR #198's receiver-side dispatcher can write the new agent into their
local swarm_members table.

Five cases:
- happy path: join broadcasts to N existing members with a valid envelope
- payload (#199): broadcast includes endpoint and joined_at fields
- transient failure: one member returning 500 does not fail the join
- idempotent re-broadcast: fan-out twice produces compatible envelopes
- no-key fallback: missing AGENT_PRIVATE_KEY_PATH skips broadcast cleanly
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.broadcast import (
    broadcast_member_joined,
    build_broadcast_envelope,
)
from src.server.config import (
    AgentConfig,
    RateLimitConfig,
    ServerConfig,
    WakeConfig,
    WakeEndpointConfig,
)
from src.state.database import DatabaseManager
from src.state.models.member import SwarmMember, SwarmMembership, SwarmSettings
from src.state.repositories.membership import MembershipRepository
from tests.conftest import _make_jwt

SWARM_ID = "550e8400-e29b-41d4-a716-446655440000"
MASTER_ID = "master-agent"
MASTER_ENDPOINT = "https://master.example.com/swarm"
NEW_AGENT_ID = "new-agent-100"
NEW_AGENT_ENDPOINT = "https://new100.example.com/swarm"
NEW_AGENT_PUBKEY_B64 = "bmV3LWFnZW50LXB1YmxpYy1rZXk="
EXISTING_MEMBER_A = "existing-a"
EXISTING_MEMBER_A_ENDPOINT = "https://a.example.com/swarm"
EXISTING_MEMBER_B = "existing-b"
EXISTING_MEMBER_B_ENDPOINT = "https://b.example.com/swarm"


def _write_master_key(tmp_path: Path) -> tuple[Path, Ed25519PrivateKey, bytes]:
    """Generate and persist a master Ed25519 private key for the server."""
    private_key = Ed25519PrivateKey.generate()
    raw = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption(),
    )
    path = tmp_path / "agent.key"
    path.write_bytes(raw)
    pub_bytes = private_key.public_key().public_bytes_raw()
    return path, private_key, pub_bytes


def _seed_swarm_with_members(
    db_path: Path,
    master_pubkey_b64: str,
    extra_members: list[SwarmMember],
) -> None:
    """Seed a swarm with master + supplied additional members."""

    async def _seed() -> None:
        db = DatabaseManager(db_path)
        await db.initialize()
        master = SwarmMember(
            agent_id=MASTER_ID,
            endpoint=MASTER_ENDPOINT,
            public_key=master_pubkey_b64,
            joined_at=datetime.now(timezone.utc),
        )
        members = (master,) + tuple(extra_members)
        swarm = SwarmMembership(
            swarm_id=SWARM_ID,
            name="Test Swarm",
            master=MASTER_ID,
            members=members,
            joined_at=datetime.now(timezone.utc),
            settings=SwarmSettings(
                allow_member_invite=False, require_approval=False,
            ),
        )
        async with db.connection() as conn:
            await MembershipRepository(conn).create_swarm(swarm)
        await db.close()

    asyncio.run(_seed())


def _make_config(
    db_path: Path, master_pubkey_b64: str, key_path: Path | None,
) -> ServerConfig:
    return ServerConfig(
        agent=AgentConfig(
            agent_id=MASTER_ID,
            endpoint=MASTER_ENDPOINT,
            public_key=master_pubkey_b64,
            protocol_version="0.1.0",
            capabilities=("message", "system", "notification"),
            private_key_path=key_path,
        ),
        rate_limit=RateLimitConfig(messages_per_minute=600),
        db_path=db_path,
        wake=WakeConfig(enabled=False, endpoint=""),
        wake_endpoint=WakeEndpointConfig(enabled=False),
    )


def _build_join_body(private_key: Ed25519PrivateKey) -> dict:
    token = _make_jwt(
        {"alg": "EdDSA", "typ": "JWT"},
        {
            "swarm_id": SWARM_ID,
            "master": MASTER_ID,
            "endpoint": MASTER_ENDPOINT,
            "iat": 1700000000,
        },
        private_key,
    )
    return {
        "type": "system",
        "action": "join_request",
        "invite_token": token,
        "sender": {
            "agent_id": NEW_AGENT_ID,
            "endpoint": NEW_AGENT_ENDPOINT,
            "public_key": NEW_AGENT_PUBKEY_B64,
        },
    }


def _build_async_post_mock(
    *, status_code: int = 200,
) -> tuple[AsyncMock, AsyncMock]:
    """Return (mock_factory_return, mock_post) for httpx.AsyncClient."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_post = AsyncMock(return_value=mock_response)
    mock_instance = AsyncMock()
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.__aexit__.return_value = None
    mock_instance.post = mock_post
    return mock_instance, mock_post


class TestBuildBroadcastEnvelope:
    """Unit tests for the wire envelope shape (#199 + #200)."""

    def test_envelope_is_real_system_type(self) -> None:
        """The receiver dispatcher only fires on type=system, not type=message."""
        private_key = Ed25519PrivateKey.generate()
        envelope = build_broadcast_envelope(
            swarm_id=SWARM_ID,
            master_id=MASTER_ID,
            master_endpoint=MASTER_ENDPOINT,
            master_private_key=private_key,
            new_agent_id=NEW_AGENT_ID,
            new_agent_endpoint=NEW_AGENT_ENDPOINT,
            joined_at=datetime(2026, 4, 27, 6, 21, 32, tzinfo=timezone.utc),
        )
        assert envelope["type"] == "system"
        assert envelope["recipient"] == "broadcast"
        assert envelope["sender"]["agent_id"] == MASTER_ID
        assert envelope["sender"]["endpoint"] == MASTER_ENDPOINT

    def test_payload_includes_endpoint_and_joined_at(self) -> None:
        """#199: receiver needs both fields to populate swarm_members."""
        private_key = Ed25519PrivateKey.generate()
        envelope = build_broadcast_envelope(
            swarm_id=SWARM_ID,
            master_id=MASTER_ID,
            master_endpoint=MASTER_ENDPOINT,
            master_private_key=private_key,
            new_agent_id=NEW_AGENT_ID,
            new_agent_endpoint=NEW_AGENT_ENDPOINT,
            joined_at=datetime(2026, 4, 27, 6, 21, 32, tzinfo=timezone.utc),
        )
        content = json.loads(envelope["content"])
        assert content["action"] == "member_joined"
        assert content["agent_id"] == NEW_AGENT_ID
        assert content["endpoint"] == NEW_AGENT_ENDPOINT
        assert content["joined_at"] == "2026-04-27T06:21:32.000Z"
        assert content["swarm_id"] == SWARM_ID

    def test_envelope_has_signature(self) -> None:
        """Signature field is non-empty base64 — receiver MAY verify."""
        private_key = Ed25519PrivateKey.generate()
        envelope = build_broadcast_envelope(
            swarm_id=SWARM_ID,
            master_id=MASTER_ID,
            master_endpoint=MASTER_ENDPOINT,
            master_private_key=private_key,
            new_agent_id=NEW_AGENT_ID,
            new_agent_endpoint=NEW_AGENT_ENDPOINT,
            joined_at=datetime.now(timezone.utc),
        )
        assert envelope["signature"]
        # Signature decodes as base64 — implies it is not a placeholder
        # like the test fixtures use.
        decoded = base64.b64decode(envelope["signature"])
        assert len(decoded) == 64  # Ed25519 signatures are 64 bytes


class TestBroadcastMemberJoined:
    """Unit tests for the cross-host fan-out (#200)."""

    def test_fans_out_to_all_existing_members_except_new_and_master(
        self, tmp_path: Path,
    ) -> None:
        private_key = Ed25519PrivateKey.generate()
        master_pubkey_b64 = base64.b64encode(
            private_key.public_key().public_bytes_raw(),
        ).decode("ascii")

        members = [
            SwarmMember(
                agent_id=MASTER_ID, endpoint=MASTER_ENDPOINT,
                public_key=master_pubkey_b64,
                joined_at=datetime.now(timezone.utc),
            ),
            SwarmMember(
                agent_id=EXISTING_MEMBER_A, endpoint=EXISTING_MEMBER_A_ENDPOINT,
                public_key="cHViLWE=",
                joined_at=datetime.now(timezone.utc),
            ),
            SwarmMember(
                agent_id=EXISTING_MEMBER_B, endpoint=EXISTING_MEMBER_B_ENDPOINT,
                public_key="cHViLWI=",
                joined_at=datetime.now(timezone.utc),
            ),
            SwarmMember(
                agent_id=NEW_AGENT_ID, endpoint=NEW_AGENT_ENDPOINT,
                public_key=NEW_AGENT_PUBKEY_B64,
                joined_at=datetime.now(timezone.utc),
            ),
        ]

        mock_instance, mock_post = _build_async_post_mock(status_code=200)
        with patch(
            "src.server.broadcast.httpx.AsyncClient",
            return_value=mock_instance,
        ):
            delivered, attempted = asyncio.run(broadcast_member_joined(
                members=members,
                new_agent_id=NEW_AGENT_ID,
                swarm_id=SWARM_ID,
                master_id=MASTER_ID,
                master_endpoint=MASTER_ENDPOINT,
                master_private_key=private_key,
                new_agent_endpoint=NEW_AGENT_ENDPOINT,
                joined_at=datetime.now(timezone.utc),
            ))

        assert attempted == 2
        assert delivered == 2
        # Both A and B were POSTed to /message — and ONLY them
        urls_called = {call.args[0] for call in mock_post.call_args_list}
        assert urls_called == {
            f"{EXISTING_MEMBER_A_ENDPOINT}/message",
            f"{EXISTING_MEMBER_B_ENDPOINT}/message",
        }

    def test_transient_failure_does_not_abort_other_deliveries(self) -> None:
        """A 500 from one member must not stop deliveries to the rest (#200 brief)."""
        import httpx

        private_key = Ed25519PrivateKey.generate()
        members = [
            SwarmMember(
                agent_id=MASTER_ID, endpoint=MASTER_ENDPOINT,
                public_key="bWFzdGVy",
                joined_at=datetime.now(timezone.utc),
            ),
            SwarmMember(
                agent_id=EXISTING_MEMBER_A, endpoint=EXISTING_MEMBER_A_ENDPOINT,
                public_key="cHViLWE=",
                joined_at=datetime.now(timezone.utc),
            ),
            SwarmMember(
                agent_id=EXISTING_MEMBER_B, endpoint=EXISTING_MEMBER_B_ENDPOINT,
                public_key="cHViLWI=",
                joined_at=datetime.now(timezone.utc),
            ),
            SwarmMember(
                agent_id=NEW_AGENT_ID, endpoint=NEW_AGENT_ENDPOINT,
                public_key=NEW_AGENT_PUBKEY_B64,
                joined_at=datetime.now(timezone.utc),
            ),
        ]

        ok_response = MagicMock()
        ok_response.status_code = 200

        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_instance.post = AsyncMock(side_effect=[
            httpx.ConnectError("connection refused"),  # member A
            ok_response,                                 # member B
        ])

        with patch(
            "src.server.broadcast.httpx.AsyncClient",
            return_value=mock_instance,
        ):
            delivered, attempted = asyncio.run(broadcast_member_joined(
                members=members,
                new_agent_id=NEW_AGENT_ID,
                swarm_id=SWARM_ID,
                master_id=MASTER_ID,
                master_endpoint=MASTER_ENDPOINT,
                master_private_key=private_key,
                new_agent_endpoint=NEW_AGENT_ENDPOINT,
                joined_at=datetime.now(timezone.utc),
            ))

        assert attempted == 2
        assert delivered == 1  # one ok, one failed
        # Both attempts were made — the failure did not skip member B
        assert mock_instance.post.call_count == 2

    def test_no_other_members_returns_zero_zero(self) -> None:
        """A swarm where master+new are the only members emits no broadcasts."""
        private_key = Ed25519PrivateKey.generate()
        members = [
            SwarmMember(
                agent_id=MASTER_ID, endpoint=MASTER_ENDPOINT,
                public_key="bWFzdGVy",
                joined_at=datetime.now(timezone.utc),
            ),
            SwarmMember(
                agent_id=NEW_AGENT_ID, endpoint=NEW_AGENT_ENDPOINT,
                public_key=NEW_AGENT_PUBKEY_B64,
                joined_at=datetime.now(timezone.utc),
            ),
        ]
        mock_instance, mock_post = _build_async_post_mock()
        with patch(
            "src.server.broadcast.httpx.AsyncClient",
            return_value=mock_instance,
        ):
            delivered, attempted = asyncio.run(broadcast_member_joined(
                members=members,
                new_agent_id=NEW_AGENT_ID,
                swarm_id=SWARM_ID,
                master_id=MASTER_ID,
                master_endpoint=MASTER_ENDPOINT,
                master_private_key=private_key,
                new_agent_endpoint=NEW_AGENT_ENDPOINT,
                joined_at=datetime.now(timezone.utc),
            ))
        assert attempted == 0
        assert delivered == 0
        mock_post.assert_not_called()


class TestJoinEndpointTriggersBroadcast:
    """Integration: the join handler wires the broadcast into the join flow."""

    def test_join_broadcasts_to_existing_members_and_persists_locally(
        self, standard_headers: dict, tmp_path: Path,
    ) -> None:
        """End-to-end: join → local notification persisted + cross-host fan-out.

        Verifies BOTH halves: the master's own inbox gets the system row
        (from the existing notify_member_joined path) AND the broadcast
        helper is invoked with the right shape (the cross-host fix #200).
        """
        key_path, private_key, pub_bytes = _write_master_key(tmp_path)
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_broadcast.db"

        existing = SwarmMember(
            agent_id=EXISTING_MEMBER_A,
            endpoint=EXISTING_MEMBER_A_ENDPOINT,
            public_key="cHViLWE=",
            joined_at=datetime.now(timezone.utc),
        )
        _seed_swarm_with_members(db_path, master_pubkey_b64, [existing])
        config = _make_config(db_path, master_pubkey_b64, key_path)
        body = _build_join_body(private_key)

        mock_instance, mock_post = _build_async_post_mock(status_code=200)
        with patch(
            "src.server.broadcast.httpx.AsyncClient",
            return_value=mock_instance,
        ):
            with TestClient(create_app(config)) as client:
                response = client.post(
                    "/swarm/join", json=body, headers=standard_headers,
                )

        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

        # Master-side local notification (existing behaviour, with new
        # endpoint+joined_at fields per #199)
        async def _check_inbox() -> None:
            db = DatabaseManager(db_path)
            await db.initialize()
            async with db.connection() as conn:
                cursor = await conn.execute(
                    "SELECT content FROM inbox WHERE message_type = 'system'",
                )
                rows = await cursor.fetchall()
            assert len(rows) == 1
            content = json.loads(rows[0]["content"])
            assert content["action"] == "member_joined"
            assert content["agent_id"] == NEW_AGENT_ID
            assert content["endpoint"] == NEW_AGENT_ENDPOINT
            assert "joined_at" in content
            await db.close()

        asyncio.run(_check_inbox())

        # Cross-host broadcast (the fix #200): one POST to existing member A
        assert mock_post.call_count == 1
        call_url = mock_post.call_args.args[0]
        assert call_url == f"{EXISTING_MEMBER_A_ENDPOINT}/message"
        broadcast_payload = mock_post.call_args.kwargs["json"]
        assert broadcast_payload["type"] == "system"
        assert broadcast_payload["recipient"] == "broadcast"
        assert broadcast_payload["sender"]["agent_id"] == MASTER_ID
        sent_content = json.loads(broadcast_payload["content"])
        assert sent_content["action"] == "member_joined"
        assert sent_content["agent_id"] == NEW_AGENT_ID
        assert sent_content["endpoint"] == NEW_AGENT_ENDPOINT
        assert "joined_at" in sent_content

    def test_transient_member_failure_does_not_fail_join(
        self, standard_headers: dict, tmp_path: Path,
    ) -> None:
        """A delivery failure to one member must NOT cause the join to error."""
        import httpx

        key_path, private_key, pub_bytes = _write_master_key(tmp_path)
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_partial_fail.db"

        member_a = SwarmMember(
            agent_id=EXISTING_MEMBER_A,
            endpoint=EXISTING_MEMBER_A_ENDPOINT,
            public_key="cHViLWE=",
            joined_at=datetime.now(timezone.utc),
        )
        member_b = SwarmMember(
            agent_id=EXISTING_MEMBER_B,
            endpoint=EXISTING_MEMBER_B_ENDPOINT,
            public_key="cHViLWI=",
            joined_at=datetime.now(timezone.utc),
        )
        _seed_swarm_with_members(
            db_path, master_pubkey_b64, [member_a, member_b],
        )
        config = _make_config(db_path, master_pubkey_b64, key_path)
        body = _build_join_body(private_key)

        ok_response = MagicMock()
        ok_response.status_code = 200
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__.return_value = None
        mock_instance.post = AsyncMock(side_effect=[
            httpx.ConnectError("connection refused"),  # first member
            ok_response,                                 # second member
        ])
        with patch(
            "src.server.broadcast.httpx.AsyncClient",
            return_value=mock_instance,
        ):
            with TestClient(create_app(config)) as client:
                response = client.post(
                    "/swarm/join", json=body, headers=standard_headers,
                )

        # Join must still succeed despite per-member delivery failure
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"
        # Both POSTs were attempted (no early-exit on failure)
        assert mock_instance.post.call_count == 2

    def test_idempotent_re_broadcast_envelope_shape(self) -> None:
        """Defense-in-depth: rebroadcasting with the same inputs is safe.

        PR #198's receiver dispatcher uses INSERT OR IGNORE on swarm_members,
        so the same payload arriving twice produces exactly one row. This
        test asserts the wire envelope shape is consistent across calls
        (same sender, same recipient, same content payload — message_id
        and timestamp differ by design).
        """
        private_key = Ed25519PrivateKey.generate()
        joined_at = datetime(2026, 4, 27, 6, 21, 32, tzinfo=timezone.utc)
        envelope_a = build_broadcast_envelope(
            swarm_id=SWARM_ID,
            master_id=MASTER_ID,
            master_endpoint=MASTER_ENDPOINT,
            master_private_key=private_key,
            new_agent_id=NEW_AGENT_ID,
            new_agent_endpoint=NEW_AGENT_ENDPOINT,
            joined_at=joined_at,
        )
        envelope_b = build_broadcast_envelope(
            swarm_id=SWARM_ID,
            master_id=MASTER_ID,
            master_endpoint=MASTER_ENDPOINT,
            master_private_key=private_key,
            new_agent_id=NEW_AGENT_ID,
            new_agent_endpoint=NEW_AGENT_ENDPOINT,
            joined_at=joined_at,
        )
        # message_id + timestamp + signature differ (timestamps capture the
        # broadcast moment, not the join moment); content payload is identical
        assert envelope_a["message_id"] != envelope_b["message_id"]
        assert envelope_a["content"] == envelope_b["content"]
        assert envelope_a["sender"] == envelope_b["sender"]
        assert envelope_a["recipient"] == envelope_b["recipient"]
        assert envelope_a["type"] == envelope_b["type"]

    def test_missing_private_key_skips_broadcast_but_join_succeeds(
        self, standard_headers: dict, tmp_path: Path,
    ) -> None:
        """Missing AGENT_PRIVATE_KEY_PATH degrades gracefully (legacy mode)."""
        # Generate the master key for token signing only — do NOT write it
        # to disk. private_key_path=None on config skips the broadcast.
        private_key = Ed25519PrivateKey.generate()
        pub_bytes = private_key.public_key().public_bytes_raw()
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_no_key.db"

        existing = SwarmMember(
            agent_id=EXISTING_MEMBER_A,
            endpoint=EXISTING_MEMBER_A_ENDPOINT,
            public_key="cHViLWE=",
            joined_at=datetime.now(timezone.utc),
        )
        _seed_swarm_with_members(db_path, master_pubkey_b64, [existing])
        config = _make_config(db_path, master_pubkey_b64, key_path=None)
        body = _build_join_body(private_key)

        mock_instance, mock_post = _build_async_post_mock()
        with patch(
            "src.server.broadcast.httpx.AsyncClient",
            return_value=mock_instance,
        ):
            with TestClient(create_app(config)) as client:
                response = client.post(
                    "/swarm/join", json=body, headers=standard_headers,
                )

        assert response.status_code == 200
        # No broadcast attempted (key absent)
        mock_post.assert_not_called()

        # Local notification still persisted
        async def _check_inbox() -> None:
            db = DatabaseManager(db_path)
            await db.initialize()
            async with db.connection() as conn:
                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM inbox WHERE message_type = 'system'",
                )
                count = (await cursor.fetchone())[0]
            assert count == 1
            await db.close()

        asyncio.run(_check_inbox())

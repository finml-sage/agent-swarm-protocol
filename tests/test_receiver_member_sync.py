"""Tests for receiver-side swarm_members sync on system lifecycle events.

Issue #197: when a member receives a system message with action=member_joined,
member_left, or member_kicked, the local swarm_members table must be updated
so direct A2A sends can route. Without this dispatch, members can only reach
a newly-joined agent via broadcast.

Four cases:
- happy path: member_joined POST + /swarm/info fetched populates 5+4 cols
- /swarm/info unreachable: fetch fails, swarm_members unchanged, msg queued
- idempotent re-receipt: same member_joined twice = exactly one row
- symmetric leave/kick: deletes from swarm_members, public_keys survives
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.config import (
    AgentConfig,
    RateLimitConfig,
    ServerConfig,
    WakeConfig,
    WakeEndpointConfig,
)
from src.state.database import DatabaseManager
from src.state.models.member import SwarmMember, SwarmMembership, SwarmSettings
from src.state.models.public_key import PublicKeyEntry
from src.state.repositories.keys import PublicKeyRepository
from src.state.repositories.membership import MembershipRepository

SWARM_ID = "550e8400-e29b-41d4-a716-446655440000"
LOCAL_AGENT_ID = "test-agent-001"
MASTER_AGENT_ID = "master-agent"
NEW_AGENT_ID = "new-agent"
NEW_AGENT_ENDPOINT = "https://new.example.com/swarm"
NEW_AGENT_PUBKEY = "TEbdvaX/2wLtQRodO+9L4XvqDkrvjwTfITNja66wcl4="
MASTER_ENDPOINT = "https://master.example.com/swarm"
MASTER_PUBKEY = "bWFzdGVyLWtleS1iYXNlNjQtcGFkZGluZw=="
LOCAL_ENDPOINT = "https://test.example.com"
LOCAL_PUBKEY = "dGVzdC1wdWJsaWMta2V5LWJhc2U2NA=="


def _seed_swarm(db_path: Path) -> None:
    """Seed a swarm with master + the local (receiving) agent as members."""

    async def _seed() -> None:
        db = DatabaseManager(db_path)
        await db.initialize()
        master = SwarmMember(
            agent_id=MASTER_AGENT_ID,
            endpoint=MASTER_ENDPOINT,
            public_key=MASTER_PUBKEY,
            joined_at=datetime.now(timezone.utc),
        )
        local = SwarmMember(
            agent_id=LOCAL_AGENT_ID,
            endpoint=LOCAL_ENDPOINT,
            public_key=LOCAL_PUBKEY,
            joined_at=datetime.now(timezone.utc),
        )
        swarm = SwarmMembership(
            swarm_id=SWARM_ID,
            name="Test Swarm",
            master=MASTER_AGENT_ID,
            members=(master, local),
            joined_at=datetime.now(timezone.utc),
            settings=SwarmSettings(
                allow_member_invite=False, require_approval=False,
            ),
        )
        async with db.connection() as conn:
            await MembershipRepository(conn).create_swarm(swarm)
        await db.close()

    asyncio.run(_seed())


def _make_config(db_path: Path) -> ServerConfig:
    return ServerConfig(
        agent=AgentConfig(
            agent_id=LOCAL_AGENT_ID,
            endpoint=LOCAL_ENDPOINT,
            public_key=LOCAL_PUBKEY,
            protocol_version="0.1.0",
            capabilities=("message", "system", "notification"),
        ),
        rate_limit=RateLimitConfig(messages_per_minute=600),
        db_path=db_path,
        wake=WakeConfig(enabled=False, endpoint=""),
        wake_endpoint=WakeEndpointConfig(enabled=False),
    )


def _system_message(
    action: str,
    target_agent_id: str,
    *,
    message_id: str = "00000000-0000-0000-0000-000000000001",
    sender_endpoint: str = NEW_AGENT_ENDPOINT,
    sender_id: str = MASTER_AGENT_ID,
    extra_content: dict | None = None,
) -> dict:
    """Build a wire-format system message for the receiver endpoint."""
    content: dict = {
        "type": "system",
        "action": action,
        "agent_id": target_agent_id,
        "swarm_id": SWARM_ID,
    }
    if extra_content:
        content.update(extra_content)
    return {
        "protocol_version": "0.1.0",
        "message_id": message_id,
        "timestamp": "2026-04-27T06:21:32.000Z",
        "sender": {"agent_id": sender_id, "endpoint": sender_endpoint},
        "recipient": LOCAL_AGENT_ID,
        "swarm_id": SWARM_ID,
        "type": "system",
        "content": json.dumps(content),
        "signature": "dGVzdC1zaWduYXR1cmUtYmFzZTY0",
    }


def _build_swarm_info_mock(public_key: str = NEW_AGENT_PUBKEY) -> AsyncMock:
    """Build an AsyncMock httpx.AsyncClient that returns a /swarm/info response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "agent_id": NEW_AGENT_ID,
        "endpoint": NEW_AGENT_ENDPOINT,
        "public_key": public_key,
        "protocol_version": "0.1.0",
        "capabilities": ["message", "system"],
    }
    mock_instance = AsyncMock()
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.__aexit__.return_value = None
    mock_instance.get = AsyncMock(return_value=mock_response)
    return mock_instance


def _row_to_dict(row) -> dict:
    return {key: row[key] for key in row.keys()}


def _read_table(db_path: Path, table: str, where: str = "") -> list[dict]:
    async def _read() -> list[dict]:
        db = DatabaseManager(db_path)
        await db.initialize()
        async with db.connection() as conn:
            sql = f"SELECT * FROM {table}"
            if where:
                sql = f"{sql} WHERE {where}"
            cursor = await conn.execute(sql)
            rows = await cursor.fetchall()
        await db.close()
        return [_row_to_dict(r) for r in rows]

    return asyncio.run(_read())


class TestMemberJoinedReceiverDispatch:
    """Receiving member_joined writes swarm_members and pre-warms public_keys."""

    def test_happy_path_writes_swarm_members_and_public_keys(
        self, tmp_path: Path,
    ) -> None:
        """member_joined POST → /swarm/info fetched → 5 cols + cache populated."""
        db_path = tmp_path / "happy.db"
        _seed_swarm(db_path)
        config = _make_config(db_path)

        with patch(
            "src.server.system_dispatch.httpx.AsyncClient",
        ) as mock_client_factory:
            mock_instance = _build_swarm_info_mock()
            mock_client_factory.return_value = mock_instance
            with TestClient(create_app(config)) as client:
                msg = _system_message(
                    action="member_joined",
                    target_agent_id=NEW_AGENT_ID,
                    sender_endpoint=NEW_AGENT_ENDPOINT,
                    extra_content={
                        "endpoint": NEW_AGENT_ENDPOINT,
                        "joined_at": "2026-04-27T06:21:32.000Z",
                    },
                )
                response = client.post(
                    "/swarm/message",
                    json=msg,
                    headers={
                        "Content-Type": "application/json",
                        "X-Agent-ID": MASTER_AGENT_ID,
                        "X-Swarm-Protocol": "0.1.0",
                    },
                )
                assert response.status_code == 200
                assert response.json()["status"] == "queued"

        # Verify /info URL convention: endpoint already includes /swarm,
        # so route is appended bare. Compare to client/operations.py
        # join URL pattern (`{endpoint.rstrip('/')}/join`).
        mock_instance.get.assert_called_once()
        call_url = mock_instance.get.call_args[0][0]
        assert call_url == f"{NEW_AGENT_ENDPOINT}/info", (
            f"Expected /info appended to swarm endpoint, got: {call_url}"
        )
        call_headers = mock_instance.get.call_args.kwargs["headers"]
        assert call_headers["X-Agent-ID"] == LOCAL_AGENT_ID
        assert call_headers["X-Swarm-Protocol"] == "0.1.0"

        members = _read_table(
            db_path, "swarm_members",
            where=f"agent_id = '{NEW_AGENT_ID}' AND swarm_id = '{SWARM_ID}'",
        )
        assert len(members) == 1
        row = members[0]
        # All 5 NOT NULL columns present
        assert row["agent_id"] == NEW_AGENT_ID
        assert row["swarm_id"] == SWARM_ID
        assert row["endpoint"] == NEW_AGENT_ENDPOINT
        assert row["public_key"] == NEW_AGENT_PUBKEY
        assert row["joined_at"] == "2026-04-27T06:21:32.000Z"

        keys = _read_table(
            db_path, "public_keys", where=f"agent_id = '{NEW_AGENT_ID}'",
        )
        assert len(keys) == 1
        assert keys[0]["public_key"] == NEW_AGENT_PUBKEY
        assert keys[0]["endpoint"] == NEW_AGENT_ENDPOINT
        assert keys[0]["fetched_at"]  # any non-empty ISO timestamp

    def test_swarm_info_unreachable_does_not_crash(
        self, tmp_path: Path,
    ) -> None:
        """When /swarm/info is unreachable, msg stays queued, tables unchanged."""
        import httpx

        db_path = tmp_path / "unreachable.db"
        _seed_swarm(db_path)
        config = _make_config(db_path)

        with patch(
            "src.server.system_dispatch.httpx.AsyncClient",
        ) as mock_client_factory:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.get = AsyncMock(
                side_effect=httpx.ConnectError("connection refused"),
            )
            mock_client_factory.return_value = mock_instance
            with TestClient(create_app(config)) as client:
                msg = _system_message(
                    action="member_joined",
                    target_agent_id=NEW_AGENT_ID,
                    sender_endpoint=NEW_AGENT_ENDPOINT,
                    extra_content={
                        "endpoint": NEW_AGENT_ENDPOINT,
                        "joined_at": "2026-04-27T06:21:32.000Z",
                    },
                )
                response = client.post(
                    "/swarm/message",
                    json=msg,
                    headers={
                        "Content-Type": "application/json",
                        "X-Agent-ID": MASTER_AGENT_ID,
                        "X-Swarm-Protocol": "0.1.0",
                    },
                )
                # Message must still be accepted
                assert response.status_code == 200
                assert response.json()["status"] == "queued"

        # No row was inserted because the public_key fetch failed
        members = _read_table(
            db_path, "swarm_members",
            where=f"agent_id = '{NEW_AGENT_ID}'",
        )
        assert members == []
        keys = _read_table(
            db_path, "public_keys", where=f"agent_id = '{NEW_AGENT_ID}'",
        )
        assert keys == []

        # And the inbox row exists (message was persisted before dispatch)
        inbox = _read_table(
            db_path, "inbox",
            where=f"sender_id = '{MASTER_AGENT_ID}'",
        )
        assert len(inbox) == 1

    def test_idempotent_re_receipt_does_not_duplicate(
        self, tmp_path: Path,
    ) -> None:
        """Receiving the same member_joined twice → exactly one row, no exception."""
        db_path = tmp_path / "idempotent.db"
        _seed_swarm(db_path)
        config = _make_config(db_path)

        with patch(
            "src.server.system_dispatch.httpx.AsyncClient",
        ) as mock_client_factory:
            mock_client_factory.return_value = _build_swarm_info_mock()
            with TestClient(create_app(config)) as client:
                msg_id_a = "00000000-0000-0000-0000-00000000aaaa"
                msg_id_b = "00000000-0000-0000-0000-00000000bbbb"
                msg_a = _system_message(
                    action="member_joined",
                    target_agent_id=NEW_AGENT_ID,
                    message_id=msg_id_a,
                    sender_endpoint=NEW_AGENT_ENDPOINT,
                    extra_content={
                        "endpoint": NEW_AGENT_ENDPOINT,
                        "joined_at": "2026-04-27T06:21:32.000Z",
                    },
                )
                msg_b = dict(msg_a)
                msg_b["message_id"] = msg_id_b
                # Second receipt has DIFFERENT message_id (so the inbox
                # idempotency at message level does not deduplicate it)
                # but identical payload — INSERT OR IGNORE on swarm_members
                # must still produce exactly one row.
                resp_a = client.post(
                    "/swarm/message", json=msg_a,
                    headers={
                        "Content-Type": "application/json",
                        "X-Agent-ID": MASTER_AGENT_ID,
                        "X-Swarm-Protocol": "0.1.0",
                    },
                )
                resp_b = client.post(
                    "/swarm/message", json=msg_b,
                    headers={
                        "Content-Type": "application/json",
                        "X-Agent-ID": MASTER_AGENT_ID,
                        "X-Swarm-Protocol": "0.1.0",
                    },
                )
                assert resp_a.status_code == 200
                assert resp_b.status_code == 200

        members = _read_table(
            db_path, "swarm_members",
            where=f"agent_id = '{NEW_AGENT_ID}' AND swarm_id = '{SWARM_ID}'",
        )
        assert len(members) == 1


class TestMemberRemovedReceiverDispatch:
    """Receiving member_left or member_kicked deletes from swarm_members only."""

    def test_member_left_deletes_swarm_members_keeps_public_keys(
        self, tmp_path: Path,
    ) -> None:
        """member_left POST → swarm_members row removed, public_keys cache survives."""
        db_path = tmp_path / "left.db"
        _seed_swarm(db_path)
        config = _make_config(db_path)

        # Pre-populate the new agent into swarm_members AND public_keys
        # (simulating an earlier successful member_joined receipt).
        async def _seed_new_member() -> None:
            db = DatabaseManager(db_path)
            await db.initialize()
            async with db.connection() as conn:
                await conn.execute(
                    "INSERT INTO swarm_members "
                    "(agent_id, swarm_id, endpoint, public_key, joined_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        NEW_AGENT_ID, SWARM_ID, NEW_AGENT_ENDPOINT,
                        NEW_AGENT_PUBKEY, "2026-04-27T06:21:32.000Z",
                    ),
                )
                await conn.commit()
                await PublicKeyRepository(conn).store(PublicKeyEntry(
                    agent_id=NEW_AGENT_ID,
                    public_key=NEW_AGENT_PUBKEY,
                    fetched_at=datetime.now(timezone.utc),
                    endpoint=NEW_AGENT_ENDPOINT,
                ))
            await db.close()

        asyncio.run(_seed_new_member())

        with TestClient(create_app(config)) as client:
            msg = _system_message(
                action="member_left",
                target_agent_id=NEW_AGENT_ID,
                sender_id=NEW_AGENT_ID,
                sender_endpoint=NEW_AGENT_ENDPOINT,
            )
            response = client.post(
                "/swarm/message", json=msg,
                headers={
                    "Content-Type": "application/json",
                    "X-Agent-ID": NEW_AGENT_ID,
                    "X-Swarm-Protocol": "0.1.0",
                },
            )
            assert response.status_code == 200

        members = _read_table(
            db_path, "swarm_members",
            where=f"agent_id = '{NEW_AGENT_ID}' AND swarm_id = '{SWARM_ID}'",
        )
        assert members == []

        keys = _read_table(
            db_path, "public_keys", where=f"agent_id = '{NEW_AGENT_ID}'",
        )
        assert len(keys) == 1
        assert keys[0]["public_key"] == NEW_AGENT_PUBKEY

    def test_member_kicked_deletes_swarm_members_keeps_public_keys(
        self, tmp_path: Path,
    ) -> None:
        """member_kicked POST: swarm_members row removed, public_keys cache survives."""
        db_path = tmp_path / "kicked.db"
        _seed_swarm(db_path)
        config = _make_config(db_path)

        async def _seed_new_member() -> None:
            db = DatabaseManager(db_path)
            await db.initialize()
            async with db.connection() as conn:
                await conn.execute(
                    "INSERT INTO swarm_members "
                    "(agent_id, swarm_id, endpoint, public_key, joined_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        NEW_AGENT_ID, SWARM_ID, NEW_AGENT_ENDPOINT,
                        NEW_AGENT_PUBKEY, "2026-04-27T06:21:32.000Z",
                    ),
                )
                await conn.commit()
                await PublicKeyRepository(conn).store(PublicKeyEntry(
                    agent_id=NEW_AGENT_ID,
                    public_key=NEW_AGENT_PUBKEY,
                    fetched_at=datetime.now(timezone.utc),
                    endpoint=NEW_AGENT_ENDPOINT,
                ))
            await db.close()

        asyncio.run(_seed_new_member())

        with TestClient(create_app(config)) as client:
            msg = _system_message(
                action="member_kicked",
                target_agent_id=NEW_AGENT_ID,
                sender_id=MASTER_AGENT_ID,
                sender_endpoint=MASTER_ENDPOINT,
                extra_content={
                    "initiated_by": MASTER_AGENT_ID,
                    "reason": "Spamming",
                },
            )
            response = client.post(
                "/swarm/message", json=msg,
                headers={
                    "Content-Type": "application/json",
                    "X-Agent-ID": MASTER_AGENT_ID,
                    "X-Swarm-Protocol": "0.1.0",
                },
            )
            assert response.status_code == 200

        members = _read_table(
            db_path, "swarm_members",
            where=f"agent_id = '{NEW_AGENT_ID}' AND swarm_id = '{SWARM_ID}'",
        )
        assert members == []

        keys = _read_table(
            db_path, "public_keys", where=f"agent_id = '{NEW_AGENT_ID}'",
        )
        assert len(keys) == 1, "public_keys cache must survive membership churn"

    def test_member_left_for_unknown_agent_is_noop(
        self, tmp_path: Path,
    ) -> None:
        """member_left for an agent not in swarm_members is a clean no-op."""
        db_path = tmp_path / "unknown_left.db"
        _seed_swarm(db_path)
        config = _make_config(db_path)

        with TestClient(create_app(config)) as client:
            msg = _system_message(
                action="member_left",
                target_agent_id="never-was-a-member",
                sender_id="never-was-a-member",
                sender_endpoint="https://noexist.example.com",
            )
            response = client.post(
                "/swarm/message", json=msg,
                headers={
                    "Content-Type": "application/json",
                    "X-Agent-ID": "never-was-a-member",
                    "X-Swarm-Protocol": "0.1.0",
                },
            )
            assert response.status_code == 200

        # No effect on the seeded master + local rows
        members = _read_table(db_path, "swarm_members")
        agent_ids = {m["agent_id"] for m in members}
        assert agent_ids == {MASTER_AGENT_ID, LOCAL_AGENT_ID}

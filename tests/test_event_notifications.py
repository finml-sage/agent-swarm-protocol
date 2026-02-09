"""Tests for swarm lifecycle event notifications."""
import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.config import AgentConfig, ServerConfig
from src.server.notifications import (
    LifecycleAction,
    LifecycleEvent,
    build_notification_message,
    notify_member_joined,
    notify_member_kicked,
    notify_member_left,
    notify_member_muted,
    notify_member_unmuted,
    persist_notification,
)
from src.state.database import DatabaseManager
from src.state.models.inbox import InboxMessage, InboxStatus
from src.state.models.member import SwarmMember, SwarmMembership, SwarmSettings
from src.state.repositories.inbox import InboxRepository
from src.state.repositories.membership import MembershipRepository
from tests.conftest import _make_jwt

SWARM_ID = "550e8400-e29b-41d4-a716-446655440000"


def _seed_swarm(db_path: Path, master_pubkey_b64: str) -> None:
    """Seed a swarm with a master agent."""

    async def _seed() -> None:
        db = DatabaseManager(db_path)
        await db.initialize()
        master = SwarmMember(
            agent_id="master-agent",
            endpoint="https://master.example.com/swarm",
            public_key=master_pubkey_b64,
            joined_at=datetime.now(timezone.utc),
        )
        swarm = SwarmMembership(
            swarm_id=SWARM_ID,
            name="Test Swarm",
            master="master-agent",
            members=(master,),
            joined_at=datetime.now(timezone.utc),
            settings=SwarmSettings(
                allow_member_invite=False, require_approval=False,
            ),
        )
        async with db.connection() as conn:
            await MembershipRepository(conn).create_swarm(swarm)
        await db.close()

    asyncio.run(_seed())


class TestBuildNotificationMessage:
    """Unit tests for build_notification_message."""

    def test_builds_member_joined_message(self) -> None:
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_JOINED,
            swarm_id=SWARM_ID,
            agent_id="new-agent",
        )
        msg = build_notification_message(event)
        assert msg.swarm_id == SWARM_ID
        assert msg.sender_id == "new-agent"
        assert msg.message_type == "system"
        content = json.loads(msg.content)
        assert content["type"] == "system"
        assert content["action"] == "member_joined"
        assert content["agent_id"] == "new-agent"
        assert content["swarm_id"] == SWARM_ID
        assert content["initiated_by"] is None
        assert content["reason"] is None

    def test_builds_member_kicked_message_with_initiator(self) -> None:
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_KICKED,
            swarm_id=SWARM_ID,
            agent_id="bad-agent",
            initiated_by="master-agent",
            reason="Spamming",
        )
        msg = build_notification_message(event)
        assert msg.sender_id == "master-agent"
        content = json.loads(msg.content)
        assert content["action"] == "member_kicked"
        assert content["agent_id"] == "bad-agent"
        assert content["initiated_by"] == "master-agent"
        assert content["reason"] == "Spamming"

    def test_builds_member_left_message(self) -> None:
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_LEFT,
            swarm_id=SWARM_ID,
            agent_id="leaving-agent",
        )
        msg = build_notification_message(event)
        content = json.loads(msg.content)
        assert content["action"] == "member_left"
        assert content["agent_id"] == "leaving-agent"

    def test_builds_member_muted_message(self) -> None:
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_MUTED,
            swarm_id=SWARM_ID,
            agent_id="noisy-agent",
            initiated_by="master-agent",
            reason="Too chatty",
        )
        msg = build_notification_message(event)
        content = json.loads(msg.content)
        assert content["action"] == "member_muted"
        assert content["reason"] == "Too chatty"

    def test_builds_member_unmuted_message(self) -> None:
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_UNMUTED,
            swarm_id=SWARM_ID,
            agent_id="quiet-agent",
            initiated_by="master-agent",
        )
        msg = build_notification_message(event)
        content = json.loads(msg.content)
        assert content["action"] == "member_unmuted"

    def test_message_has_valid_uuid(self) -> None:
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_JOINED,
            swarm_id=SWARM_ID,
            agent_id="agent",
        )
        msg = build_notification_message(event)
        # Should not raise
        import uuid

        uuid.UUID(msg.message_id)

    def test_message_has_recent_timestamp(self) -> None:
        before = datetime.now(timezone.utc)
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_JOINED,
            swarm_id=SWARM_ID,
            agent_id="agent",
        )
        msg = build_notification_message(event)
        after = datetime.now(timezone.utc)
        assert before <= msg.received_at <= after

    def test_message_status_is_unread(self) -> None:
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_JOINED,
            swarm_id=SWARM_ID,
            agent_id="agent",
        )
        msg = build_notification_message(event)
        assert msg.status == InboxStatus.UNREAD


class TestPersistNotification:
    """Tests for persisting notifications to the database."""

    @pytest.mark.asyncio
    async def test_persists_notification_to_db(self, tmp_path: Path) -> None:
        db = DatabaseManager(tmp_path / "notify.db")
        await db.initialize()
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_JOINED,
            swarm_id=SWARM_ID,
            agent_id="new-agent",
        )
        msg = await persist_notification(db, event)
        async with db.connection() as conn:
            repo = InboxRepository(conn)
            stored = await repo.get_by_id(msg.message_id)
        assert stored is not None
        assert stored.message_type == "system"
        assert stored.swarm_id == SWARM_ID
        assert stored.status == InboxStatus.UNREAD
        content = json.loads(stored.content)
        assert content["action"] == "member_joined"
        await db.close()

    @pytest.mark.asyncio
    async def test_notify_member_joined_helper(self, tmp_path: Path) -> None:
        db = DatabaseManager(tmp_path / "joined.db")
        await db.initialize()
        msg = await notify_member_joined(db, SWARM_ID, "agent-a")
        content = json.loads(msg.content)
        assert content["action"] == "member_joined"
        assert content["agent_id"] == "agent-a"
        await db.close()

    @pytest.mark.asyncio
    async def test_notify_member_left_helper(self, tmp_path: Path) -> None:
        db = DatabaseManager(tmp_path / "left.db")
        await db.initialize()
        msg = await notify_member_left(db, SWARM_ID, "agent-b")
        content = json.loads(msg.content)
        assert content["action"] == "member_left"
        assert content["agent_id"] == "agent-b"
        await db.close()

    @pytest.mark.asyncio
    async def test_notify_member_kicked_helper(self, tmp_path: Path) -> None:
        db = DatabaseManager(tmp_path / "kicked.db")
        await db.initialize()
        msg = await notify_member_kicked(
            db, SWARM_ID, "bad-agent", "master-agent", reason="Violation",
        )
        content = json.loads(msg.content)
        assert content["action"] == "member_kicked"
        assert content["initiated_by"] == "master-agent"
        assert content["reason"] == "Violation"
        await db.close()

    @pytest.mark.asyncio
    async def test_notify_member_muted_helper(self, tmp_path: Path) -> None:
        db = DatabaseManager(tmp_path / "muted.db")
        await db.initialize()
        msg = await notify_member_muted(
            db, SWARM_ID, "noisy", "master-agent", reason="Spam",
        )
        content = json.loads(msg.content)
        assert content["action"] == "member_muted"
        assert content["reason"] == "Spam"
        await db.close()

    @pytest.mark.asyncio
    async def test_notify_member_unmuted_helper(self, tmp_path: Path) -> None:
        db = DatabaseManager(tmp_path / "unmuted.db")
        await db.initialize()
        msg = await notify_member_unmuted(db, SWARM_ID, "quiet", "master-agent")
        content = json.loads(msg.content)
        assert content["action"] == "member_unmuted"
        await db.close()


class TestJoinEndpointNotification:
    """Integration tests: join endpoint generates member_joined notification."""

    def test_new_join_persists_notification(
        self,
        agent_config: AgentConfig,
        master_keypair: tuple,
        standard_headers: dict,
        tmp_path: Path,
    ) -> None:
        """A genuinely new join should persist a member_joined notification."""
        private_key, pub_bytes = master_keypair
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_notify.db"
        _seed_swarm(db_path, master_pubkey_b64)
        config = ServerConfig(agent=agent_config, db_path=db_path)
        token = _make_jwt(
            {"alg": "EdDSA", "typ": "JWT"},
            {
                "swarm_id": SWARM_ID,
                "master": "master-agent",
                "endpoint": "https://master.example.com/swarm",
                "iat": 1700000000,
            },
            private_key,
        )
        body = {
            "type": "system",
            "action": "join_request",
            "invite_token": token,
            "sender": {
                "agent_id": "new-agent-001",
                "endpoint": "https://new.example.com",
                "public_key": "bmV3LWFnZW50LXB1YmxpYy1rZXk=",
            },
        }
        with TestClient(create_app(config)) as c:
            response = c.post("/swarm/join", json=body, headers=standard_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

        # Verify notification was persisted to inbox
        async def _check() -> None:
            db = DatabaseManager(db_path)
            await db.initialize()
            async with db.connection() as conn:
                cursor = await conn.execute(
                    "SELECT * FROM inbox WHERE message_type = 'system'",
                )
                rows = await cursor.fetchall()
            assert len(rows) == 1
            content = json.loads(rows[0]["content"])
            assert content["action"] == "member_joined"
            assert content["agent_id"] == "new-agent-001"
            assert content["swarm_id"] == SWARM_ID
            await db.close()

        asyncio.run(_check())

    def test_idempotent_rejoin_no_duplicate_notification(
        self,
        agent_config: AgentConfig,
        master_keypair: tuple,
        standard_headers: dict,
        tmp_path: Path,
    ) -> None:
        """An idempotent re-join should NOT persist a duplicate notification."""
        private_key, pub_bytes = master_keypair
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_idem_notify.db"
        _seed_swarm(db_path, master_pubkey_b64)
        config = ServerConfig(agent=agent_config, db_path=db_path)
        token = _make_jwt(
            {"alg": "EdDSA", "typ": "JWT"},
            {
                "swarm_id": SWARM_ID,
                "master": "master-agent",
                "endpoint": "https://master.example.com/swarm",
                "iat": 1700000000,
            },
            private_key,
        )
        body = {
            "type": "system",
            "action": "join_request",
            "invite_token": token,
            "sender": {
                "agent_id": "new-agent-002",
                "endpoint": "https://new2.example.com",
                "public_key": "bmV3LWFnZW50LXB1YmxpYy1rZXk=",
            },
        }
        with TestClient(create_app(config)) as c:
            first = c.post("/swarm/join", json=body, headers=standard_headers)
            second = c.post("/swarm/join", json=body, headers=standard_headers)
        assert first.status_code == 200
        assert second.status_code == 200

        # Only one notification should exist (from the first join)
        async def _check() -> None:
            db = DatabaseManager(db_path)
            await db.initialize()
            async with db.connection() as conn:
                cursor = await conn.execute(
                    "SELECT * FROM inbox WHERE message_type = 'system'",
                )
                rows = await cursor.fetchall()
            assert len(rows) == 1
            content = json.loads(rows[0]["content"])
            assert content["action"] == "member_joined"
            assert content["agent_id"] == "new-agent-002"
            await db.close()

        asyncio.run(_check())

    def test_existing_member_rejoin_no_notification(
        self,
        agent_config: AgentConfig,
        master_keypair: tuple,
        standard_headers: dict,
        tmp_path: Path,
    ) -> None:
        """Master agent re-joining should not generate a notification."""
        private_key, pub_bytes = master_keypair
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_master_no_notify.db"
        _seed_swarm(db_path, master_pubkey_b64)
        config = ServerConfig(agent=agent_config, db_path=db_path)
        token = _make_jwt(
            {"alg": "EdDSA", "typ": "JWT"},
            {
                "swarm_id": SWARM_ID,
                "master": "master-agent",
                "endpoint": "https://master.example.com/swarm",
                "iat": 1700000000,
            },
            private_key,
        )
        body = {
            "type": "system",
            "action": "join_request",
            "invite_token": token,
            "sender": {
                "agent_id": "master-agent",
                "endpoint": "https://master.example.com/swarm",
                "public_key": master_pubkey_b64,
            },
        }
        with TestClient(create_app(config)) as c:
            response = c.post("/swarm/join", json=body, headers=standard_headers)
        assert response.status_code == 200

        # No notification for existing member
        async def _check() -> None:
            db = DatabaseManager(db_path)
            await db.initialize()
            async with db.connection() as conn:
                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM inbox WHERE message_type = 'system'",
                )
                count = (await cursor.fetchone())[0]
            assert count == 0
            await db.close()

        asyncio.run(_check())


class TestLifecycleEventModel:
    """Tests for the LifecycleEvent dataclass."""

    def test_lifecycle_action_values(self) -> None:
        assert LifecycleAction.MEMBER_JOINED.value == "member_joined"
        assert LifecycleAction.MEMBER_LEFT.value == "member_left"
        assert LifecycleAction.MEMBER_KICKED.value == "member_kicked"
        assert LifecycleAction.MEMBER_MUTED.value == "member_muted"
        assert LifecycleAction.MEMBER_UNMUTED.value == "member_unmuted"

    def test_event_defaults(self) -> None:
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_JOINED,
            swarm_id=SWARM_ID,
            agent_id="agent",
        )
        assert event.initiated_by is None
        assert event.reason is None

    def test_event_with_all_fields(self) -> None:
        event = LifecycleEvent(
            action=LifecycleAction.MEMBER_KICKED,
            swarm_id=SWARM_ID,
            agent_id="bad-agent",
            initiated_by="master",
            reason="Violation",
        )
        assert event.action == LifecycleAction.MEMBER_KICKED
        assert event.initiated_by == "master"
        assert event.reason == "Violation"

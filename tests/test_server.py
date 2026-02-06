"""Tests for the FastAPI server."""
import asyncio
import base64
import json

from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.config import (
    ServerConfig, AgentConfig, RateLimitConfig, WakeConfig, WakeEndpointConfig,
)
from src.state.database import DatabaseManager
from src.state.models.member import SwarmMember, SwarmMembership, SwarmSettings
from src.state.repositories.membership import MembershipRepository
from tests.conftest import _b64url_encode, _make_jwt


SWARM_ID = "550e8400-e29b-41d4-a716-446655440000"

_NO_WAKE = WakeConfig(enabled=False, endpoint="")
_NO_WAKE_EP = WakeEndpointConfig(enabled=False)


def _seed_swarm(db_path: Path, master_pubkey_b64: str) -> None:
    """Seed a swarm into the database synchronously (for test setup)."""
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
            settings=SwarmSettings(allow_member_invite=False, require_approval=False),
        )
        async with db.connection() as conn:
            await MembershipRepository(conn).create_swarm(swarm)
        await db.close()
    asyncio.run(_seed())


def _seed_approval_swarm(db_path: Path, master_pubkey_b64: str) -> None:
    """Seed a swarm that requires approval."""
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
            name="Approval Swarm",
            master="master-agent",
            members=(master,),
            joined_at=datetime.now(timezone.utc),
            settings=SwarmSettings(allow_member_invite=False, require_approval=True),
        )
        async with db.connection() as conn:
            await MembershipRepository(conn).create_swarm(swarm)
        await db.close()
    asyncio.run(_seed())


class TestMessageEndpoint:
    def test_accepts_valid_message(self, client: TestClient, valid_message: dict, standard_headers: dict) -> None:
        response = client.post("/swarm/message", json=valid_message, headers=standard_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

    def test_rejects_missing_required_fields(self, client: TestClient, valid_message: dict, standard_headers: dict) -> None:
        del valid_message["signature"]
        response = client.post("/swarm/message", json=valid_message, headers=standard_headers)
        assert response.status_code == 422

    def test_rejects_invalid_uuid(self, client: TestClient, valid_message: dict, standard_headers: dict) -> None:
        valid_message["message_id"] = "not-a-uuid"
        response = client.post("/swarm/message", json=valid_message, headers=standard_headers)
        assert response.status_code == 422

    def test_rejects_http_endpoint(self, client: TestClient, valid_message: dict, standard_headers: dict) -> None:
        valid_message["sender"]["endpoint"] = "http://insecure.example.com"
        response = client.post("/swarm/message", json=valid_message, headers=standard_headers)
        assert response.status_code == 422


class TestJoinEndpoint:
    def test_accepts_valid_join_request(
        self, agent_config: AgentConfig, master_keypair, standard_headers: dict, tmp_path: Path,
    ) -> None:
        private_key, pub_bytes = master_keypair
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_accept.db"
        _seed_swarm(db_path, master_pubkey_b64)
        config = ServerConfig(
            agent=agent_config, db_path=db_path,
            wake=_NO_WAKE, wake_endpoint=_NO_WAKE_EP,
        )
        token = _make_jwt(
            {"alg": "EdDSA", "typ": "JWT"},
            {"swarm_id": SWARM_ID, "master": "master-agent",
             "endpoint": "https://master.example.com/swarm", "iat": 1700000000},
            private_key,
        )
        body = {
            "type": "system", "action": "join_request", "invite_token": token,
            "sender": {"agent_id": "new-agent-789", "endpoint": "https://newagent.example.com",
                       "public_key": "bmV3LWFnZW50LXB1YmxpYy1rZXk="},
        }
        with TestClient(create_app(config)) as c:
            response = c.post("/swarm/join", json=body, headers=standard_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["swarm_id"] == SWARM_ID
        assert data["swarm_name"] == "Test Swarm"
        agent_ids = [m["agent_id"] for m in data["members"]]
        assert "new-agent-789" in agent_ids
        assert "master-agent" in agent_ids

    def test_rejects_invalid_token_structure(
        self, client: TestClient, standard_headers: dict,
    ) -> None:
        body = {
            "type": "system", "action": "join_request",
            "invite_token": "not-a-jwt",
            "sender": {"agent_id": "agent", "endpoint": "https://a.com",
                       "public_key": "a2V5"},
        }
        response = client.post("/swarm/join", json=body, headers=standard_headers)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_TOKEN"

    def test_rejects_token_for_unknown_swarm(
        self, agent_config: AgentConfig, standard_headers: dict, tmp_path: Path,
    ) -> None:
        private_key = Ed25519PrivateKey.generate()
        token = _make_jwt(
            {"alg": "EdDSA", "typ": "JWT"},
            {"swarm_id": "nonexistent-swarm-id", "master": "m",
             "endpoint": "https://m.com", "iat": 1700000000},
            private_key,
        )
        db_path = tmp_path / "join_unknown.db"
        config = ServerConfig(
            agent=agent_config, db_path=db_path,
            wake=_NO_WAKE, wake_endpoint=_NO_WAKE_EP,
        )
        body = {
            "type": "system", "action": "join_request", "invite_token": token,
            "sender": {"agent_id": "agent", "endpoint": "https://a.com",
                       "public_key": "a2V5"},
        }
        with TestClient(create_app(config)) as c:
            response = c.post("/swarm/join", json=body, headers=standard_headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SWARM_NOT_FOUND"

    def test_rejects_forged_token(
        self, agent_config: AgentConfig, master_keypair, standard_headers: dict, tmp_path: Path,
    ) -> None:
        _, pub_bytes = master_keypair
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_forged.db"
        _seed_swarm(db_path, master_pubkey_b64)
        config = ServerConfig(
            agent=agent_config, db_path=db_path,
            wake=_NO_WAKE, wake_endpoint=_NO_WAKE_EP,
        )
        wrong_key = Ed25519PrivateKey.generate()
        token = _make_jwt(
            {"alg": "EdDSA", "typ": "JWT"},
            {"swarm_id": SWARM_ID, "master": "master-agent",
             "endpoint": "https://master.example.com/swarm", "iat": 1700000000},
            wrong_key,
        )
        body = {
            "type": "system", "action": "join_request", "invite_token": token,
            "sender": {"agent_id": "evil-agent", "endpoint": "https://evil.com",
                       "public_key": "ZXZpbC1rZXk="},
        }
        with TestClient(create_app(config)) as c:
            response = c.post("/swarm/join", json=body, headers=standard_headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_SIGNATURE"

    def test_idempotent_join_returns_membership(
        self, agent_config: AgentConfig, master_keypair, standard_headers: dict, tmp_path: Path,
    ) -> None:
        """Joining twice with the same agent returns 200 both times."""
        private_key, pub_bytes = master_keypair
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_idempotent.db"
        _seed_swarm(db_path, master_pubkey_b64)
        config = ServerConfig(
            agent=agent_config, db_path=db_path,
            wake=_NO_WAKE, wake_endpoint=_NO_WAKE_EP,
        )
        token = _make_jwt(
            {"alg": "EdDSA", "typ": "JWT"},
            {"swarm_id": SWARM_ID, "master": "master-agent",
             "endpoint": "https://master.example.com/swarm", "iat": 1700000000},
            private_key,
        )
        body = {
            "type": "system", "action": "join_request", "invite_token": token,
            "sender": {"agent_id": "new-agent-789", "endpoint": "https://newagent.example.com",
                       "public_key": "bmV3LWFnZW50LXB1YmxpYy1rZXk="},
        }
        with TestClient(create_app(config)) as c:
            first = c.post("/swarm/join", json=body, headers=standard_headers)
            second = c.post("/swarm/join", json=body, headers=standard_headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["status"] == "accepted"
        assert second.json()["status"] == "accepted"
        assert first.json()["swarm_id"] == second.json()["swarm_id"]
        assert set(m["agent_id"] for m in first.json()["members"]) == \
               set(m["agent_id"] for m in second.json()["members"])

    def test_existing_member_returns_membership(
        self, agent_config: AgentConfig, master_keypair, standard_headers: dict, tmp_path: Path,
    ) -> None:
        """Master agent (already seeded) can re-join and get 200 with membership data."""
        private_key, pub_bytes = master_keypair
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_existing.db"
        _seed_swarm(db_path, master_pubkey_b64)
        config = ServerConfig(
            agent=agent_config, db_path=db_path,
            wake=_NO_WAKE, wake_endpoint=_NO_WAKE_EP,
        )
        token = _make_jwt(
            {"alg": "EdDSA", "typ": "JWT"},
            {"swarm_id": SWARM_ID, "master": "master-agent",
             "endpoint": "https://master.example.com/swarm", "iat": 1700000000},
            private_key,
        )
        body = {
            "type": "system", "action": "join_request", "invite_token": token,
            "sender": {"agent_id": "master-agent", "endpoint": "https://master.example.com/swarm",
                       "public_key": master_pubkey_b64},
        }
        with TestClient(create_app(config)) as c:
            response = c.post("/swarm/join", json=body, headers=standard_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert data["swarm_id"] == SWARM_ID
        assert data["swarm_name"] == "Test Swarm"
        assert any(m["agent_id"] == "master-agent" for m in data["members"])

    def test_pending_when_approval_required(
        self, agent_config: AgentConfig, master_keypair, standard_headers: dict, tmp_path: Path,
    ) -> None:
        private_key, pub_bytes = master_keypair
        master_pubkey_b64 = base64.b64encode(pub_bytes).decode("ascii")
        db_path = tmp_path / "join_approval.db"
        _seed_approval_swarm(db_path, master_pubkey_b64)
        config = ServerConfig(
            agent=agent_config, db_path=db_path,
            wake=_NO_WAKE, wake_endpoint=_NO_WAKE_EP,
        )
        token = _make_jwt(
            {"alg": "EdDSA", "typ": "JWT"},
            {"swarm_id": SWARM_ID, "master": "master-agent",
             "endpoint": "https://master.example.com/swarm", "iat": 1700000000},
            private_key,
        )
        body = {
            "type": "system", "action": "join_request", "invite_token": token,
            "sender": {"agent_id": "new-agent", "endpoint": "https://new.example.com",
                       "public_key": "bmV3LWtleQ=="},
        }
        with TestClient(create_app(config)) as c:
            response = c.post("/swarm/join", json=body, headers=standard_headers)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "pending"
        assert data["swarm_id"] == SWARM_ID


class TestHealthEndpoint:
    def test_returns_healthy_status(self, client: TestClient, standard_headers: dict) -> None:
        response = client.get("/swarm/health", headers=standard_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestInfoEndpoint:
    def test_returns_agent_info(self, client: TestClient, standard_headers: dict) -> None:
        response = client.get("/swarm/info", headers=standard_headers)
        assert response.status_code == 200
        assert response.json()["agent_id"] == "test-agent-001"


class TestRateLimitMiddleware:
    def test_returns_429_when_limit_exceeded(self, agent_config: AgentConfig, valid_message: dict, standard_headers: dict, tmp_path: Path) -> None:
        config = ServerConfig(
            agent=agent_config, rate_limit=RateLimitConfig(messages_per_minute=3),
            db_path=tmp_path / "ratelimit.db",
            wake=_NO_WAKE, wake_endpoint=_NO_WAKE_EP,
        )
        with TestClient(create_app(config)) as c:
            for _ in range(3):
                c.post("/swarm/message", json=valid_message, headers=standard_headers)
            response = c.post("/swarm/message", json=valid_message, headers=standard_headers)
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    def test_rate_limit_headers_present(self, client: TestClient, valid_message: dict, standard_headers: dict) -> None:
        response = client.post("/swarm/message", json=valid_message, headers=standard_headers)
        assert "X-RateLimit-Limit" in response.headers

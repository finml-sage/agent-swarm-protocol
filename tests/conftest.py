"""Pytest fixtures for server tests."""
import base64
import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from src.server.app import create_app
from src.server.config import (
    ServerConfig, AgentConfig, RateLimitConfig, WakeConfig, WakeEndpointConfig,
)


def _b64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_jwt(header: dict, payload: dict, private_key: Ed25519PrivateKey) -> str:
    """Create a signed JWT for testing."""
    header_b64 = _b64url_encode(json.dumps(header).encode())
    payload_b64 = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header_b64}.{payload_b64}"
    signature = private_key.sign(signing_input.encode("ascii"))
    sig_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


@pytest.fixture
def agent_config() -> AgentConfig:
    return AgentConfig(
        agent_id="test-agent-001", endpoint="https://test.example.com",
        public_key="dGVzdC1wdWJsaWMta2V5LWJhc2U2NA==", protocol_version="0.1.0",
        capabilities=("message", "system", "notification"), name="Test Agent", description="Agent for testing",
    )


@pytest.fixture
def server_config(agent_config: AgentConfig, tmp_path: Path) -> ServerConfig:
    return ServerConfig(
        agent=agent_config, rate_limit=RateLimitConfig(messages_per_minute=60, join_requests_per_hour=10),
        queue_max_size=100, db_path=tmp_path / "test.db",
        wake=WakeConfig(enabled=False, endpoint=""),
        wake_endpoint=WakeEndpointConfig(enabled=False),
    )


@pytest.fixture
def client(server_config: ServerConfig) -> TestClient:
    app = create_app(server_config)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def valid_message() -> dict:
    return {
        "protocol_version": "0.1.0", "message_id": "550e8400-e29b-41d4-a716-446655440000",
        "timestamp": "2026-02-05T14:30:00.000Z",
        "sender": {"agent_id": "sender-agent-123", "endpoint": "https://sender.example.com"},
        "recipient": "test-agent-001", "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
        "type": "message", "content": "Hello from test", "signature": "dGVzdC1zaWduYXR1cmUtYmFzZTY0",
    }


@pytest.fixture
def master_keypair():
    """Generate Ed25519 keypair for the swarm master."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes_raw()
    return private_key, public_bytes


@pytest.fixture
def valid_join_request(master_keypair) -> dict:
    """Build a join request with a properly signed invite token."""
    private_key, _ = master_keypair
    header = {"alg": "EdDSA", "typ": "JWT"}
    payload = {
        "swarm_id": "550e8400-e29b-41d4-a716-446655440000",
        "master": "master-agent",
        "endpoint": "https://master.example.com/swarm",
        "iat": 1700000000,
    }
    token = _make_jwt(header, payload, private_key)
    return {
        "type": "system", "action": "join_request", "invite_token": token,
        "sender": {"agent_id": "new-agent-789", "endpoint": "https://newagent.example.com", "public_key": "bmV3LWFnZW50LXB1YmxpYy1rZXk="},
    }


@pytest.fixture
def standard_headers() -> dict:
    return {"Content-Type": "application/json", "X-Agent-ID": "sender-agent-123", "X-Swarm-Protocol": "0.1.0"}

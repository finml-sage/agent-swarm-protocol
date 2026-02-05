"""Pytest fixtures for server tests."""
import pytest
from fastapi.testclient import TestClient
from src.server.app import create_app
from src.server.config import ServerConfig, AgentConfig, RateLimitConfig


@pytest.fixture
def agent_config() -> AgentConfig:
    return AgentConfig(
        agent_id="test-agent-001", endpoint="https://test.example.com",
        public_key="dGVzdC1wdWJsaWMta2V5LWJhc2U2NA==", protocol_version="0.1.0",
        capabilities=("message", "system", "notification"), name="Test Agent", description="Agent for testing",
    )


@pytest.fixture
def server_config(agent_config: AgentConfig) -> ServerConfig:
    return ServerConfig(agent=agent_config, rate_limit=RateLimitConfig(messages_per_minute=60, join_requests_per_hour=10), queue_max_size=100)


@pytest.fixture
def client(server_config: ServerConfig) -> TestClient:
    return TestClient(create_app(server_config))


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
def valid_join_request() -> dict:
    return {
        "type": "system", "action": "join_request", "invite_token": "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.test",
        "sender": {"agent_id": "new-agent-789", "endpoint": "https://newagent.example.com", "public_key": "bmV3LWFnZW50LXB1YmxpYy1rZXk="},
    }


@pytest.fixture
def standard_headers() -> dict:
    return {"Content-Type": "application/json", "X-Agent-ID": "sender-agent-123", "X-Swarm-Protocol": "0.1.0"}

"""Tests for the FastAPI server."""
from fastapi.testclient import TestClient
from src.server.app import create_app
from src.server.config import ServerConfig, AgentConfig, RateLimitConfig


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
    def test_accepts_valid_join_request(self, client: TestClient, valid_join_request: dict, standard_headers: dict) -> None:
        response = client.post("/swarm/join", json=valid_join_request, headers=standard_headers)
        assert response.status_code == 202
        assert response.json()["status"] == "pending"


class TestHealthEndpoint:
    def test_returns_healthy_status(self, client: TestClient, standard_headers: dict) -> None:
        response = client.get("/swarm/health", headers=standard_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_returns_degraded_when_queue_full(self, agent_config: AgentConfig, standard_headers: dict) -> None:
        config = ServerConfig(agent=agent_config, rate_limit=RateLimitConfig(messages_per_minute=100), queue_max_size=10)
        client = TestClient(create_app(config))
        for i in range(9):
            msg = {"protocol_version": "0.1.0", "message_id": f"550e8400-e29b-41d4-a716-44665544000{i}",
                   "timestamp": "2026-02-05T14:30:00.000Z", "sender": {"agent_id": "s", "endpoint": "https://s.com"},
                   "recipient": "t", "swarm_id": "660e8400-e29b-41d4-a716-446655440001", "type": "message",
                   "content": f"M{i}", "signature": "s"}
            client.post("/swarm/message", json=msg, headers=standard_headers)
        response = client.get("/swarm/health", headers=standard_headers)
        assert response.json()["status"] == "degraded"


class TestInfoEndpoint:
    def test_returns_agent_info(self, client: TestClient, standard_headers: dict) -> None:
        response = client.get("/swarm/info", headers=standard_headers)
        assert response.status_code == 200
        assert response.json()["agent_id"] == "test-agent-001"


class TestRateLimitMiddleware:
    def test_returns_429_when_limit_exceeded(self, agent_config: AgentConfig, valid_message: dict, standard_headers: dict) -> None:
        config = ServerConfig(agent=agent_config, rate_limit=RateLimitConfig(messages_per_minute=3), queue_max_size=100)
        client = TestClient(create_app(config))
        for _ in range(3):
            client.post("/swarm/message", json=valid_message, headers=standard_headers)
        response = client.post("/swarm/message", json=valid_message, headers=standard_headers)
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    def test_rate_limit_headers_present(self, client: TestClient, valid_message: dict, standard_headers: dict) -> None:
        response = client.post("/swarm/message", json=valid_message, headers=standard_headers)
        assert "X-RateLimit-Limit" in response.headers

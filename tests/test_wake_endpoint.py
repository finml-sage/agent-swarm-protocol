"""Tests for POST /api/wake endpoint."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.claude.session_manager import SessionManager
from src.server.app import create_app
from src.server.config import (
    AgentConfig,
    RateLimitConfig,
    ServerConfig,
    WakeConfig,
    WakeEndpointConfig,
)
from src.server.invoker import AgentInvoker


def _make_config(
    tmp_path: Path,
    wake_ep_enabled: bool = True,
    invoke_method: str = "noop",
    invoke_target: str = "",
    secret: str = "",
    session_timeout_minutes: int = 30,
) -> ServerConfig:
    """Build a ServerConfig with wake endpoint configured."""
    return ServerConfig(
        agent=AgentConfig(
            agent_id="test-agent-001",
            endpoint="https://test.example.com",
            public_key="dGVzdC1wdWJsaWMta2V5LWJhc2U2NA==",
            protocol_version="0.1.0",
        ),
        rate_limit=RateLimitConfig(messages_per_minute=100),
        queue_max_size=100,
        db_path=tmp_path / "wake_ep.db",
        wake=WakeConfig(enabled=False, endpoint=""),
        wake_endpoint=WakeEndpointConfig(
            enabled=wake_ep_enabled,
            invoke_method=invoke_method,
            invoke_target=invoke_target,
            secret=secret,
            session_file=str(tmp_path / "session.json"),
            session_timeout_minutes=session_timeout_minutes,
        ),
    )


def _wake_payload(
    message_id: str = "550e8400-e29b-41d4-a716-446655440000",
    swarm_id: str = "660e8400-e29b-41d4-a716-446655440001",
    sender_id: str = "sender-agent-123",
    notification_level: str = "normal",
) -> dict:
    """Return a well-formed wake request payload."""
    return {
        "message_id": message_id,
        "swarm_id": swarm_id,
        "sender_id": sender_id,
        "notification_level": notification_level,
    }


class TestWakeEndpointDisabled:
    """When wake endpoint is disabled, /api/wake is not registered."""

    def test_returns_404_when_disabled(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, wake_ep_enabled=False)
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 404


class TestWakeEndpointInvocation:
    """When wake endpoint is enabled, it invokes the agent."""

    def test_returns_invoked_with_noop(self, tmp_path: Path) -> None:
        """Noop invoker returns 'invoked' without doing anything."""
        config = _make_config(tmp_path, invoke_method="noop")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 200
        assert response.json()["status"] == "invoked"

    def test_returns_invoked_with_all_fields(self, tmp_path: Path) -> None:
        """Response contains status and no detail on success."""
        config = _make_config(tmp_path, invoke_method="noop")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        data = response.json()
        assert data["status"] == "invoked"
        assert data["detail"] is None

    def test_rejects_invalid_payload(self, tmp_path: Path) -> None:
        """Missing required fields returns 422."""
        config = _make_config(tmp_path, invoke_method="noop")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json={"message_id": "abc"})
        assert response.status_code == 422


class TestWakeEndpointSessionCheck:
    """Session-based duplicate invocation guard."""

    def test_already_active_when_session_running(self, tmp_path: Path) -> None:
        """Returns 'already_active' when agent has an active session."""
        config = _make_config(tmp_path, invoke_method="noop")
        # Pre-create an active session (uses same file the app will read)
        session_mgr = SessionManager(
            session_file=Path(config.wake_endpoint.session_file),
        )
        session_mgr.start_session("existing-session", swarm_id="test-swarm")

        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 200
        assert response.json()["status"] == "already_active"

    def test_invokes_when_session_expired(self, tmp_path: Path) -> None:
        """Invokes when the existing session has timed out."""
        # Use session_timeout_minutes=0 so the app treats session as expired
        config = _make_config(
            tmp_path, invoke_method="noop", session_timeout_minutes=0,
        )
        session_file = Path(config.wake_endpoint.session_file)
        session_mgr = SessionManager(
            session_file=session_file,
            session_timeout_minutes=0,
        )
        session_mgr.start_session("old-session", swarm_id="test-swarm")

        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 200
        assert response.json()["status"] == "invoked"

    def test_invokes_when_no_session(self, tmp_path: Path) -> None:
        """Invokes when there is no existing session."""
        config = _make_config(tmp_path, invoke_method="noop")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 200
        assert response.json()["status"] == "invoked"


class TestWakeEndpointAuth:
    """Shared secret authentication."""

    def test_rejects_missing_secret(self, tmp_path: Path) -> None:
        """Returns 403 when secret is configured but not provided."""
        config = _make_config(tmp_path, invoke_method="noop", secret="my-secret")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 403
        assert response.json()["status"] == "error"
        assert "X-Wake-Secret" in response.json()["detail"]

    def test_rejects_wrong_secret(self, tmp_path: Path) -> None:
        """Returns 403 when the wrong secret is provided."""
        config = _make_config(tmp_path, invoke_method="noop", secret="my-secret")
        with TestClient(create_app(config)) as client:
            response = client.post(
                "/api/wake",
                json=_wake_payload(),
                headers={"X-Wake-Secret": "wrong-secret"},
            )
        assert response.status_code == 403

    def test_accepts_correct_secret(self, tmp_path: Path) -> None:
        """Returns 'invoked' when the correct secret is provided."""
        config = _make_config(tmp_path, invoke_method="noop", secret="my-secret")
        with TestClient(create_app(config)) as client:
            response = client.post(
                "/api/wake",
                json=_wake_payload(),
                headers={"X-Wake-Secret": "my-secret"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "invoked"

    def test_no_auth_when_secret_empty(self, tmp_path: Path) -> None:
        """No auth check when secret is empty string."""
        config = _make_config(tmp_path, invoke_method="noop", secret="")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 200
        assert response.json()["status"] == "invoked"


class TestWakeEndpointErrors:
    """Error handling in invocation."""

    def test_returns_error_on_invocation_failure(self, tmp_path: Path) -> None:
        """Returns error status when invoker raises an exception."""
        config = _make_config(
            tmp_path,
            invoke_method="webhook",
            invoke_target="http://localhost:9999/nonexistent",
        )

        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 500
        assert response.json()["status"] == "error"
        assert response.json()["detail"] is not None


class TestAgentInvoker:
    """Unit tests for AgentInvoker."""

    def test_rejects_unknown_method(self) -> None:
        with pytest.raises(ValueError, match="Unknown invocation method"):
            AgentInvoker(method="magic", target="something")

    def test_rejects_empty_target_for_subprocess(self) -> None:
        with pytest.raises(ValueError, match="target required"):
            AgentInvoker(method="subprocess", target="")

    def test_rejects_empty_target_for_webhook(self) -> None:
        with pytest.raises(ValueError, match="target required"):
            AgentInvoker(method="webhook", target="")

    def test_noop_allows_empty_target(self) -> None:
        invoker = AgentInvoker(method="noop", target="")
        assert invoker.method == "noop"

    @pytest.mark.asyncio
    async def test_noop_invoke_succeeds(self) -> None:
        invoker = AgentInvoker(method="noop", target="")
        await invoker.invoke({"message_id": "test"})  # Should not raise


class TestWakeEndpointConfigDefaults:
    """Test WakeEndpointConfig defaults and construction."""

    def test_defaults(self) -> None:
        cfg = WakeEndpointConfig()
        assert cfg.enabled is True
        assert cfg.invoke_method == "noop"
        assert cfg.invoke_target == ""
        assert cfg.secret == ""
        assert cfg.session_file == "/root/.swarm/session.json"
        assert cfg.session_timeout_minutes == 30

    def test_custom_values(self) -> None:
        cfg = WakeEndpointConfig(
            enabled=True,
            invoke_method="subprocess",
            invoke_target="echo wake",
            secret="s3cret",
            session_file="/tmp/sess.json",
            session_timeout_minutes=10,
        )
        assert cfg.enabled is True
        assert cfg.invoke_method == "subprocess"
        assert cfg.invoke_target == "echo wake"
        assert cfg.secret == "s3cret"
        assert cfg.session_timeout_minutes == 10

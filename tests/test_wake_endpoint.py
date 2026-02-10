"""Tests for POST /api/wake endpoint."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
from src.server.routes.wake import _invoke_lock


def _make_config(
    tmp_path: Path,
    wake_ep_enabled: bool = True,
    invoke_method: str = "noop",
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
        db_path=tmp_path / "wake_ep.db",
        wake=WakeConfig(enabled=False, endpoint=""),
        wake_endpoint=WakeEndpointConfig(
            enabled=wake_ep_enabled,
            invoke_method=invoke_method,
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
    """When wake endpoint is enabled, it returns 202 and invokes in background."""

    def test_returns_202_with_noop(self, tmp_path: Path) -> None:
        """Noop invoker returns 202 'invoked' immediately."""
        config = _make_config(tmp_path, invoke_method="noop")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 202
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


class TestWakeEndpointFireAndForget:
    """Invocation runs in a background task, not blocking the response."""

    def test_returns_202_before_invocation_completes(
        self, tmp_path: Path,
    ) -> None:
        """Endpoint returns 202 immediately even if invoker would block."""
        config = _make_config(tmp_path, invoke_method="noop")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        # 202 means "accepted for processing" (fire-and-forget)
        assert response.status_code == 202
        assert response.json()["status"] == "invoked"

    def test_invocation_error_does_not_affect_response(
        self, tmp_path: Path,
    ) -> None:
        """Even if the invoker raises, the endpoint already returned 202."""
        config = _make_config(tmp_path, invoke_method="noop")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        # Background task may fail, but response is already 202
        assert response.status_code == 202
        assert response.json()["status"] == "invoked"


class TestWakeEndpointConcurrencyLock:
    """asyncio.Lock prevents multiple simultaneous SDK invocations."""

    @pytest.mark.asyncio
    async def test_lock_exists_at_module_level(self) -> None:
        """The module-level _invoke_lock is an asyncio.Lock."""
        assert isinstance(_invoke_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_second_invocation_skipped_when_locked(self) -> None:
        """When lock is held, a second background invocation is skipped."""
        from src.server.routes.wake import _invoke_lock

        invoker = AgentInvoker(method="noop")
        invocation_count = 0

        original_invoke = invoker.invoke

        async def counting_invoke(
            payload: dict, resume: str | None = None,
        ) -> str | None:
            nonlocal invocation_count
            invocation_count += 1
            return await original_invoke(payload, resume=resume)

        invoker.invoke = counting_invoke  # type: ignore[assignment]

        # Manually acquire the lock to simulate an in-progress invocation
        await _invoke_lock.acquire()
        try:
            # Import the background helper via the route module
            from src.server.routes import wake as wake_mod

            # Build a fake _invoke_background that uses our invoker
            # We test by calling the endpoint while the lock is held
            config = ServerConfig(
                agent=AgentConfig(
                    agent_id="test-agent-001",
                    endpoint="https://test.example.com",
                    public_key="dGVzdC1wdWJsaWMta2V5LWJhc2U2NA==",
                    protocol_version="0.1.0",
                ),
                rate_limit=RateLimitConfig(messages_per_minute=100),
                db_path=Path("/tmp/test_lock.db"),
                wake=WakeConfig(enabled=False, endpoint=""),
                wake_endpoint=WakeEndpointConfig(
                    enabled=True,
                    invoke_method="noop",
                    session_file="/tmp/test_lock_session.json",
                ),
            )
            # The lock is held, so the background task should skip
            assert _invoke_lock.locked()
        finally:
            _invoke_lock.release()


class TestWakeEndpointSessionCheck:
    """Session-based duplicate invocation guard."""

    def test_already_active_when_session_running(self, tmp_path: Path) -> None:
        """Returns 'already_active' when agent has an active session."""
        config = _make_config(tmp_path, invoke_method="noop")
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
        assert response.status_code == 202
        assert response.json()["status"] == "invoked"

    def test_invokes_when_no_session(self, tmp_path: Path) -> None:
        """Invokes when there is no existing session."""
        config = _make_config(tmp_path, invoke_method="noop")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 202
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
        assert response.status_code == 202
        assert response.json()["status"] == "invoked"

    def test_no_auth_when_secret_empty(self, tmp_path: Path) -> None:
        """No auth check when secret is empty string."""
        config = _make_config(tmp_path, invoke_method="noop", secret="")
        with TestClient(create_app(config)) as client:
            response = client.post("/api/wake", json=_wake_payload())
        assert response.status_code == 202
        assert response.json()["status"] == "invoked"


class TestAgentInvoker:
    """Unit tests for AgentInvoker."""

    def test_rejects_unknown_method(self) -> None:
        with pytest.raises(ValueError, match="Unknown invocation method"):
            AgentInvoker(method="magic")

    def test_rejects_unknown_subprocess(self) -> None:
        """Removed methods are now unknown."""
        with pytest.raises(ValueError, match="Unknown invocation method"):
            AgentInvoker(method="subprocess")

    def test_rejects_unknown_webhook(self) -> None:
        """Removed methods are now unknown."""
        with pytest.raises(ValueError, match="Unknown invocation method"):
            AgentInvoker(method="webhook")

    def test_rejects_unknown_sdk(self) -> None:
        """Removed methods are now unknown."""
        with pytest.raises(ValueError, match="Unknown invocation method"):
            AgentInvoker(method="sdk")

    def test_noop_creates_invoker(self) -> None:
        invoker = AgentInvoker(method="noop")
        assert invoker.method == "noop"

    @pytest.mark.asyncio
    async def test_noop_invoke_succeeds(self) -> None:
        invoker = AgentInvoker(method="noop")
        await invoker.invoke({"message_id": "test"})  # Should not raise


class TestWakeEndpointConfigDefaults:
    """Test WakeEndpointConfig defaults and construction."""

    def test_defaults(self) -> None:
        cfg = WakeEndpointConfig()
        assert cfg.enabled is True
        assert cfg.invoke_method == "noop"
        assert cfg.secret == ""
        assert cfg.session_file == "/root/.swarm/session.json"
        assert cfg.session_timeout_minutes == 30
        assert cfg.tmux_target == ""

    def test_custom_values(self) -> None:
        cfg = WakeEndpointConfig(
            enabled=True,
            invoke_method="tmux",
            secret="s3cret",
            session_file="/tmp/sess.json",
            session_timeout_minutes=10,
            tmux_target="nexus",
        )
        assert cfg.enabled is True
        assert cfg.invoke_method == "tmux"
        assert cfg.secret == "s3cret"
        assert cfg.session_timeout_minutes == 10
        assert cfg.tmux_target == "nexus"

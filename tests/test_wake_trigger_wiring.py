"""Integration tests: WakeTrigger is called after message persistence."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.config import (
    AgentConfig, RateLimitConfig, ServerConfig, WakeConfig, WakeEndpointConfig,
    _parse_bool,
)
from src.claude.wake_trigger import WakeDecision, WakeTrigger
from src.state.database import DatabaseManager
from src.state.repositories.messages import MessageRepository


def _make_config(tmp_path: Path, wake_enabled: bool = False) -> ServerConfig:
    """Build a ServerConfig with optional wake trigger.

    Explicitly disables the wake endpoint to avoid needing an invoke
    target in test context.
    """
    return ServerConfig(
        agent=AgentConfig(
            agent_id="test-agent-001",
            endpoint="https://test.example.com",
            public_key="dGVzdC1wdWJsaWMta2V5LWJhc2U2NA==",
            protocol_version="0.1.0",
        ),
        rate_limit=RateLimitConfig(messages_per_minute=100),
        queue_max_size=100,
        db_path=tmp_path / "wake.db",
        wake=WakeConfig(
            enabled=wake_enabled,
            endpoint="http://localhost:9090/api/wake" if wake_enabled else "",
            timeout=2.0,
        ),
        wake_endpoint=WakeEndpointConfig(enabled=False),
    )


def _valid_message(
    message_id: str = "550e8400-e29b-41d4-a716-446655440000",
) -> dict:
    """Return a well-formed message payload."""
    return {
        "protocol_version": "0.1.0",
        "message_id": message_id,
        "timestamp": "2026-02-05T14:30:00.000Z",
        "sender": {
            "agent_id": "sender-agent-123",
            "endpoint": "https://sender.example.com",
        },
        "recipient": "test-agent-001",
        "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
        "type": "message",
        "content": "Hello from wake trigger test",
        "signature": "dGVzdC1zaWduYXR1cmUtYmFzZTY0",
    }


class TestWakeTriggerDisabled:
    """When wake trigger is disabled, message flow is unaffected."""

    def test_message_accepted_without_wake(self, tmp_path: Path) -> None:
        """Messages are accepted normally when wake is disabled."""
        config = _make_config(tmp_path, wake_enabled=False)
        msg = _valid_message()

        with TestClient(create_app(config)) as client:
            response = client.post(
                "/swarm/message",
                json=msg,
                headers={"Content-Type": "application/json"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "queued"

    def test_no_wake_trigger_on_app_state_when_disabled(
        self, tmp_path: Path,
    ) -> None:
        """app.state.wake_trigger is None when wake is disabled."""
        config = _make_config(tmp_path, wake_enabled=False)
        app = create_app(config)

        with TestClient(app):
            assert app.state.wake_trigger is None


class TestWakeTriggerEnabled:
    """When wake trigger is enabled, it runs after message persistence."""

    def test_wake_trigger_initialized_on_app_state(
        self, tmp_path: Path,
    ) -> None:
        """app.state.wake_trigger is a WakeTrigger when enabled."""
        config = _make_config(tmp_path, wake_enabled=True)
        app = create_app(config)

        with patch("src.claude.wake_trigger.httpx.AsyncClient"):
            with TestClient(app):
                assert isinstance(app.state.wake_trigger, WakeTrigger)

    def test_wake_trigger_called_on_message(self, tmp_path: Path) -> None:
        """WakeTrigger.process_message is called after a message is persisted."""
        config = _make_config(tmp_path, wake_enabled=True)

        with patch("src.claude.wake_trigger.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.post.return_value = AsyncMock(
                status_code=200, text="",
            )
            mock_http.return_value = mock_instance

            app = create_app(config)
            with TestClient(app) as client:
                msg = _valid_message()
                response = client.post(
                    "/swarm/message",
                    json=msg,
                    headers={"Content-Type": "application/json"},
                )

            assert response.status_code == 200
            assert response.json()["status"] == "queued"
            # The httpx client was used to POST to the wake endpoint
            mock_instance.post.assert_called_once()
            call_url = mock_instance.post.call_args[0][0]
            assert call_url == "http://localhost:9090/api/wake"

    def test_wake_trigger_payload_contains_message_id(
        self, tmp_path: Path,
    ) -> None:
        """Wake POST payload includes the message_id from the received message."""
        config = _make_config(tmp_path, wake_enabled=True)

        with patch("src.claude.wake_trigger.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.post.return_value = AsyncMock(
                status_code=200, text="",
            )
            mock_http.return_value = mock_instance

            app = create_app(config)
            msg = _valid_message("550e8400-e29b-41d4-a716-446655440099")
            with TestClient(app) as client:
                client.post(
                    "/swarm/message",
                    json=msg,
                    headers={"Content-Type": "application/json"},
                )

            payload = mock_instance.post.call_args[1]["json"]
            assert payload["message_id"] == "550e8400-e29b-41d4-a716-446655440099"
            assert payload["swarm_id"] == msg["swarm_id"]
            assert payload["sender_id"] == msg["sender"]["agent_id"]

    def test_message_still_queued_on_wake_failure(
        self, tmp_path: Path,
    ) -> None:
        """Even if the wake endpoint fails, the message is still accepted."""
        config = _make_config(tmp_path, wake_enabled=True)

        with patch("src.claude.wake_trigger.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.post.return_value = AsyncMock(
                status_code=500, text="Internal error",
            )
            mock_http.return_value = mock_instance

            app = create_app(config)
            msg = _valid_message()
            with TestClient(app) as client:
                response = client.post(
                    "/swarm/message",
                    json=msg,
                    headers={"Content-Type": "application/json"},
                )

            # Message is still accepted despite wake endpoint failure
            assert response.status_code == 200
            assert response.json()["status"] == "queued"

    def test_message_persisted_before_wake(self, tmp_path: Path) -> None:
        """Message is stored in the database before wake trigger runs."""
        config = _make_config(tmp_path, wake_enabled=True)

        with patch("src.claude.wake_trigger.httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_instance.post.return_value = AsyncMock(
                status_code=200, text="",
            )
            mock_http.return_value = mock_instance

            app = create_app(config)
            msg = _valid_message()
            with TestClient(app) as client:
                client.post(
                    "/swarm/message",
                    json=msg,
                    headers={"Content-Type": "application/json"},
                )

        # Verify message was persisted
        async def _verify() -> None:
            db = DatabaseManager(config.db_path)
            await db.initialize()
            async with db.connection() as conn:
                repo = MessageRepository(conn)
                stored = await repo.get_by_id(msg["message_id"])
            assert stored is not None
            assert stored.message_id == msg["message_id"]
            await db.close()

        asyncio.run(_verify())


class TestWakeConfig:
    """Test WakeConfig defaults and env variable loading."""

    def test_wake_enabled_by_default(self) -> None:
        """WakeConfig dataclass defaults to enabled."""
        config = WakeConfig()
        assert config.enabled is True
        assert config.endpoint == "http://localhost:8080/api/wake"

    def test_wake_endpoint_enabled_by_default(self) -> None:
        """WakeEndpointConfig dataclass defaults to enabled."""
        config = WakeEndpointConfig()
        assert config.enabled is True
        assert config.invoke_method == "noop"

    def test_wake_config_values_propagated(self, tmp_path: Path) -> None:
        """WakeConfig values from constructor are used."""
        config = _make_config(tmp_path, wake_enabled=True)
        assert config.wake.enabled is True
        assert config.wake.endpoint == "http://localhost:9090/api/wake"
        assert config.wake.timeout == 2.0


class TestParseBool:
    """Test _parse_bool helper for env variable parsing."""

    def test_empty_returns_default_true(self) -> None:
        assert _parse_bool("", default=True) is True

    def test_empty_returns_default_false(self) -> None:
        assert _parse_bool("", default=False) is False

    def test_true_values(self) -> None:
        for val in ("true", "True", "TRUE", "1", "yes", "Yes"):
            assert _parse_bool(val, default=False) is True

    def test_false_values(self) -> None:
        for val in ("false", "False", "FALSE", "0", "no", "No"):
            assert _parse_bool(val, default=True) is False

    def test_unrecognised_returns_default_with_warning(self) -> None:
        """Unrecognised strings (typos) return the default and log a warning."""
        assert _parse_bool("maybe", default=True) is True
        assert _parse_bool("ture", default=True) is True
        assert _parse_bool("maybe", default=False) is False

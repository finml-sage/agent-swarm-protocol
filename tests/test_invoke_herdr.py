"""Tests for the herdr invoke method (subprocess-based, no SDK)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.app import _build_invoker
from src.server.config import WakeEndpointConfig
from src.server.invoke_herdr import HerdrInvokeConfig, invoke_herdr
from src.server.invoker import AgentInvoker


def _wake_payload(sender_id: str = "sender-agent-123") -> dict:
    return {
        "message_id": "550e8400-e29b-41d4-a716-446655440000",
        "swarm_id": "660e8400-e29b-41d4-a716-446655440001",
        "sender_id": sender_id,
        "notification_level": "normal",
    }


def _mock_process(
    returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"",
) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


class TestHerdrInvokeConfig:
    def test_defaults(self) -> None:
        cfg = HerdrInvokeConfig(target="w1:p1")
        assert cfg.target == "w1:p1"
        assert cfg.herdr_bin == "herdr"

    def test_frozen(self) -> None:
        cfg = HerdrInvokeConfig(target="w1:p1")
        with pytest.raises(AttributeError):
            cfg.target = "other"  # type: ignore[misc]


class TestInvokeHerdr:
    @pytest.mark.asyncio
    async def test_single_agent_prompt_call(self) -> None:
        proc = _mock_process()
        cfg = HerdrInvokeConfig(target="sage", herdr_bin="/opt/herdr")
        with patch(
            "src.server.invoke_herdr.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as mock_exec:
            result = await invoke_herdr(_wake_payload(), cfg)
        assert result is None
        assert mock_exec.call_count == 1
        args = mock_exec.call_args[0]
        assert args[:4] == ("/opt/herdr", "agent", "prompt", "sage")
        assert "sender-agent-123" in args[4]
        assert "\n" not in args[4]

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises_with_detail(self) -> None:
        proc = _mock_process(returncode=1, stderr=b"agent_not_found")
        cfg = HerdrInvokeConfig(target="w1:p9")
        with patch(
            "src.server.invoke_herdr.asyncio.create_subprocess_exec",
            return_value=proc,
        ), pytest.raises(RuntimeError, match="agent_not_found"):
            await invoke_herdr(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_error_on_stdout_is_reported(self) -> None:
        proc = _mock_process(returncode=2, stdout=b'{"error":"agent_blocked"}')
        cfg = HerdrInvokeConfig(target="sage")
        with patch(
            "src.server.invoke_herdr.asyncio.create_subprocess_exec",
            return_value=proc,
        ), pytest.raises(RuntimeError, match="agent_blocked"):
            await invoke_herdr(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_subprocess_timeout_kills_and_raises(self) -> None:
        proc = _mock_process()
        proc.kill = MagicMock()
        cfg = HerdrInvokeConfig(target="sage")

        def _hang(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError()

        with patch(
            "src.server.invoke_herdr.asyncio.create_subprocess_exec",
            return_value=proc,
        ), patch(
            "src.server.invoke_herdr.asyncio.wait_for",
            side_effect=_hang,
        ), pytest.raises(RuntimeError, match="timed out"):
            await invoke_herdr(_wake_payload(), cfg)
        proc.kill.assert_called_once()


class TestAgentInvokerHerdr:
    def test_herdr_requires_config(self) -> None:
        with pytest.raises(ValueError, match="WAKE_EP_HERDR_TARGET"):
            AgentInvoker(method="herdr")

    @pytest.mark.asyncio
    async def test_invoke_dispatches_to_herdr(self) -> None:
        cfg = HerdrInvokeConfig(target="w1:p1")
        invoker = AgentInvoker(method="herdr", herdr_config=cfg)
        assert invoker.method == "herdr"
        with patch(
            "src.server.invoke_herdr.invoke_herdr", new_callable=AsyncMock,
        ) as mock_invoke:
            result = await invoker.invoke(_wake_payload())
        assert result is None
        mock_invoke.assert_awaited_once()
        assert mock_invoke.call_args[0][1] is cfg


class TestBuildInvokerHerdr:
    def test_build_from_wake_endpoint_config(self) -> None:
        config = MagicMock()
        config.wake_endpoint = WakeEndpointConfig(
            invoke_method="herdr", herdr_target="w1:p1", herdr_bin="/opt/herdr",
        )
        invoker = _build_invoker(config)
        assert invoker.method == "herdr"
        assert invoker._herdr_config == HerdrInvokeConfig(
            target="w1:p1", herdr_bin="/opt/herdr",
        )


class TestEnvConfigHerdr:
    def _env(self, monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
        monkeypatch.setenv("AGENT_ID", "test-agent")
        monkeypatch.setenv("AGENT_ENDPOINT", "https://example.test/swarm")
        monkeypatch.setenv("AGENT_PUBLIC_KEY", "dGVzdA==")
        monkeypatch.setenv("WAKE_EP_SECRET", "test-secret")
        monkeypatch.setenv("WAKE_EP_INVOKE_METHOD", "herdr")
        for key, value in extra.items():
            monkeypatch.setenv(key, value)

    def test_missing_target_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.server.config import load_config_from_env

        self._env(monkeypatch)
        monkeypatch.delenv("WAKE_EP_HERDR_TARGET", raising=False)
        with pytest.raises(ValueError, match="WAKE_EP_HERDR_TARGET"):
            load_config_from_env()

    def test_target_and_bin_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.server.config import load_config_from_env

        self._env(
            monkeypatch,
            WAKE_EP_HERDR_TARGET="w1:p1",
            WAKE_EP_HERDR_BIN="/opt/herdr",
        )
        cfg = load_config_from_env().wake_endpoint
        assert cfg.invoke_method == "herdr"
        assert cfg.herdr_target == "w1:p1"
        assert cfg.herdr_bin == "/opt/herdr"

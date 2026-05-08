"""Tests for the zellij invoke method (subprocess-based, no SDK).

Mirrors ``tests/test_invoke_tmux.py`` -- same structure, same coverage
shape, plus the subprocess-timeout case that ``invoke_zellij`` adds
relative to the simpler ``invoke_tmux`` (zellij goes through the
``_run_zellij`` helper which wraps ``communicate()`` in
``asyncio.wait_for``).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.config import WakeEndpointConfig
from src.server.invoke_zellij import (
    ZellijInvokeConfig,
    _format_notification,
    invoke_zellij,
)
from src.server.invoker import _VALID_METHODS, AgentInvoker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wake_payload(
    message_id: str = "550e8400-e29b-41d4-a716-446655440000",
    swarm_id: str = "660e8400-e29b-41d4-a716-446655440001",
    sender_id: str = "sender-agent-123",
    notification_level: str = "normal",
) -> dict:
    return {
        "message_id": message_id,
        "swarm_id": swarm_id,
        "sender_id": sender_id,
        "notification_level": notification_level,
    }


def _mock_process(returncode: int = 0, stderr: bytes = b"") -> MagicMock:
    """Create a mock async subprocess with communicate()."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"", stderr))
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# Unit tests: ZellijInvokeConfig
# ---------------------------------------------------------------------------


class TestZellijInvokeConfig:
    def test_requires_zellij_session(self) -> None:
        cfg = ZellijInvokeConfig(zellij_session="codex")
        assert cfg.zellij_session == "codex"

    def test_frozen(self) -> None:
        cfg = ZellijInvokeConfig(zellij_session="codex")
        with pytest.raises(AttributeError):
            cfg.zellij_session = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Unit tests: _format_notification
# ---------------------------------------------------------------------------


class TestFormatNotification:
    def test_includes_sender(self) -> None:
        msg = _format_notification(_wake_payload())
        assert "sender-agent-123" in msg

    def test_defaults_for_missing_sender(self) -> None:
        msg = _format_notification({})
        assert "unknown" in msg

    def test_is_single_line(self) -> None:
        msg = _format_notification(_wake_payload())
        assert "\n" not in msg


# ---------------------------------------------------------------------------
# Unit tests: invoke_zellij (two separate exec calls)
# ---------------------------------------------------------------------------


class TestInvokeZellij:
    @pytest.mark.asyncio
    async def test_calls_zellij_two_step(self) -> None:
        """Verifies two separate create_subprocess_exec calls."""
        write_proc = _mock_process(returncode=0)
        send_proc = _mock_process(returncode=0)
        cfg = ZellijInvokeConfig(zellij_session="codex")
        with (
            patch(
                "src.server.invoke_zellij.asyncio.create_subprocess_exec",
                side_effect=[write_proc, send_proc],
            ) as mock_exec,
            patch(
                "src.server.invoke_zellij.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
        ):
            await invoke_zellij(_wake_payload(), cfg)

        assert mock_exec.call_count == 2
        # First call: write-chars TEXT
        write_call = mock_exec.call_args_list[0]
        assert write_call[0][0] == "zellij"
        assert write_call[0][1] == "--session"
        assert write_call[0][2] == "codex"
        assert write_call[0][3] == "action"
        assert write_call[0][4] == "write-chars"
        assert "sender-agent-123" in write_call[0][5]
        # Second call: send-keys "Enter"
        send_call = mock_exec.call_args_list[1]
        assert send_call[0] == (
            "zellij",
            "--session",
            "codex",
            "action",
            "send-keys",
            "Enter",
        )
        # Sleep between the two calls
        mock_sleep.assert_called_once_with(0.5)

    @pytest.mark.asyncio
    async def test_returns_none(self) -> None:
        """invoke_zellij returns None (no session_id)."""
        cfg = ZellijInvokeConfig(zellij_session="codex")
        with (
            patch(
                "src.server.invoke_zellij.asyncio.create_subprocess_exec",
                side_effect=[_mock_process(0), _mock_process(0)],
            ),
            patch(
                "src.server.invoke_zellij.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            result = await invoke_zellij(_wake_payload(), cfg)
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_on_write_chars_failure(self) -> None:
        """Non-zero exit from write-chars raises RuntimeError."""
        write_proc = _mock_process(
            returncode=1,
            stderr=b"session not found: codex",
        )
        cfg = ZellijInvokeConfig(zellij_session="codex")
        with patch(
            "src.server.invoke_zellij.asyncio.create_subprocess_exec",
            side_effect=[write_proc],
        ):
            with pytest.raises(RuntimeError, match="zellij write-chars failed"):
                await invoke_zellij(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_raises_on_send_keys_failure(self) -> None:
        """Non-zero exit from send-keys raises RuntimeError."""
        write_proc = _mock_process(returncode=0)
        send_proc = _mock_process(returncode=1, stderr=b"no server running")
        cfg = ZellijInvokeConfig(zellij_session="codex")
        with (
            patch(
                "src.server.invoke_zellij.asyncio.create_subprocess_exec",
                side_effect=[write_proc, send_proc],
            ),
            patch(
                "src.server.invoke_zellij.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            with pytest.raises(RuntimeError, match="zellij send-keys failed"):
                await invoke_zellij(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_error_message_includes_stderr(self) -> None:
        """RuntimeError includes stderr content from the failing call."""
        write_proc = _mock_process(returncode=1, stderr=b"no server running")
        cfg = ZellijInvokeConfig(zellij_session="codex")
        with patch(
            "src.server.invoke_zellij.asyncio.create_subprocess_exec",
            side_effect=[write_proc],
        ):
            with pytest.raises(RuntimeError, match="no server running"):
                await invoke_zellij(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_custom_session(self) -> None:
        """Zellij session from config is passed to both subprocess calls."""
        write_proc = _mock_process(returncode=0)
        send_proc = _mock_process(returncode=0)
        cfg = ZellijInvokeConfig(zellij_session="orchestrator")
        with (
            patch(
                "src.server.invoke_zellij.asyncio.create_subprocess_exec",
                side_effect=[write_proc, send_proc],
            ) as mock_exec,
            patch(
                "src.server.invoke_zellij.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            await invoke_zellij(_wake_payload(), cfg)

        write_call = mock_exec.call_args_list[0]
        assert write_call[0][2] == "orchestrator"
        send_call = mock_exec.call_args_list[1]
        assert send_call[0][2] == "orchestrator"

    @pytest.mark.asyncio
    async def test_uses_exec_not_shell(self) -> None:
        """create_subprocess_exec is used, not create_subprocess_shell."""
        write_proc = _mock_process(returncode=0)
        send_proc = _mock_process(returncode=0)
        cfg = ZellijInvokeConfig(zellij_session="codex")
        with (
            patch(
                "src.server.invoke_zellij.asyncio.create_subprocess_exec",
                side_effect=[write_proc, send_proc],
            ) as mock_exec,
            patch(
                "src.server.invoke_zellij.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "src.server.invoke_zellij.asyncio.create_subprocess_shell",
            ) as mock_shell,
        ):
            await invoke_zellij(_wake_payload(), cfg)

        assert mock_exec.call_count == 2
        mock_shell.assert_not_called()

    @pytest.mark.asyncio
    async def test_sleep_between_calls(self) -> None:
        """asyncio.sleep(0.5) is called between the two exec calls."""
        write_proc = _mock_process(returncode=0)
        send_proc = _mock_process(returncode=0)
        cfg = ZellijInvokeConfig(zellij_session="codex")
        call_order: list[str] = []

        async def track_exec(*args: object, **kwargs: object) -> MagicMock:
            call_order.append("exec")
            if len(call_order) == 1:
                return write_proc
            return send_proc

        async def track_sleep(seconds: float) -> None:
            call_order.append(f"sleep:{seconds}")

        with (
            patch(
                "src.server.invoke_zellij.asyncio.create_subprocess_exec",
                side_effect=track_exec,
            ),
            patch(
                "src.server.invoke_zellij.asyncio.sleep",
                side_effect=track_sleep,
            ),
        ):
            await invoke_zellij(_wake_payload(), cfg)

        assert call_order == ["exec", "sleep:0.5", "exec"]

    @pytest.mark.asyncio
    async def test_subprocess_timeout_kills_and_raises(self) -> None:
        """Hung zellij call raises RuntimeError and kill() is invoked."""
        # communicate() never resolves -- raise asyncio.TimeoutError on
        # the wait_for wrapping it
        write_proc = MagicMock()
        write_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        write_proc.kill = MagicMock()
        cfg = ZellijInvokeConfig(zellij_session="codex")
        with (
            patch(
                "src.server.invoke_zellij.asyncio.create_subprocess_exec",
                side_effect=[write_proc],
            ),
            patch(
                "src.server.invoke_zellij.asyncio.wait_for",
                side_effect=asyncio.TimeoutError(),
            ),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await invoke_zellij(_wake_payload(), cfg)
        write_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Unit tests: AgentInvoker with zellij method
# ---------------------------------------------------------------------------


class TestAgentInvokerZellij:
    def test_zellij_in_valid_methods(self) -> None:
        """zellij is in the _VALID_METHODS whitelist."""
        assert "zellij" in _VALID_METHODS

    def test_zellij_method_accepted(self) -> None:
        """Zellij method is accepted (no SDK required)."""
        cfg = ZellijInvokeConfig(zellij_session="codex")
        invoker = AgentInvoker(method="zellij", zellij_config=cfg)
        assert invoker.method == "zellij"

    def test_zellij_rejects_missing_config(self) -> None:
        """Zellij method raises if zellij_config is not provided."""
        with pytest.raises(ValueError, match="zellij_config required"):
            AgentInvoker(method="zellij")

    def test_unknown_method_lists_zellij_in_error(self) -> None:
        """Unknown method error message lists zellij as a valid option."""
        with pytest.raises(ValueError, match="zellij"):
            AgentInvoker(method="bogus")

    @pytest.mark.asyncio
    async def test_zellij_invoke_calls_invoke_zellij(self) -> None:
        """AgentInvoker.invoke delegates to invoke_zellij."""
        cfg = ZellijInvokeConfig(zellij_session="codex")
        invoker = AgentInvoker(method="zellij", zellij_config=cfg)
        with patch(
            "src.server.invoke_zellij.invoke_zellij",
            new_callable=AsyncMock,
        ) as mock:
            result = await invoker.invoke(_wake_payload())
        mock.assert_called_once_with(_wake_payload(), cfg)
        assert result is None

    @pytest.mark.asyncio
    async def test_zellij_invoke_dispatch_wired(self) -> None:
        """Whitelist + dispatch are both wired (no KeyError at invoke).

        Defensive test against the brief's CRITICAL note: adding to
        _VALID_METHODS without wiring the dispatch would let
        ``method='zellij'`` pass init but raise at invoke time.
        """
        cfg = ZellijInvokeConfig(zellij_session="codex")
        invoker = AgentInvoker(method="zellij", zellij_config=cfg)
        # invoke() must not raise KeyError / NotImplementedError --
        # it must reach _invoke_zellij and dispatch to the function.
        with patch(
            "src.server.invoke_zellij.invoke_zellij",
            new_callable=AsyncMock,
        ):
            result = await invoker.invoke(_wake_payload())
        assert result is None


# ---------------------------------------------------------------------------
# Unit tests: WakeEndpointConfig zellij_session field
# ---------------------------------------------------------------------------


class TestWakeEndpointConfigZellij:
    def test_zellij_session_default_empty(self) -> None:
        cfg = WakeEndpointConfig()
        assert cfg.zellij_session == ""

    def test_zellij_session_custom(self) -> None:
        cfg = WakeEndpointConfig(
            enabled=True,
            invoke_method="zellij",
            zellij_session="codex",
        )
        assert cfg.zellij_session == "codex"
        assert cfg.invoke_method == "zellij"


# ---------------------------------------------------------------------------
# Unit tests: config validation for zellij method
# ---------------------------------------------------------------------------


class TestConfigZellijValidation:
    def test_missing_zellij_session_raises(self) -> None:
        """load_config_from_env raises if zellij method lacks WAKE_EP_ZELLIJ_SESSION."""
        from src.server.config import load_config_from_env

        env = {
            "AGENT_ID": "test",
            "AGENT_ENDPOINT": "https://test.example.com",
            "AGENT_PUBLIC_KEY": "dGVzdA==",
            "WAKE_EP_INVOKE_METHOD": "zellij",
            "WAKE_EP_ZELLIJ_SESSION": "",
        }
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValueError, match="WAKE_EP_ZELLIJ_SESSION"):
                load_config_from_env()

    def test_zellij_session_set_succeeds(self) -> None:
        """load_config_from_env succeeds when zellij_session is set."""
        from src.server.config import load_config_from_env

        env = {
            "AGENT_ID": "test",
            "AGENT_ENDPOINT": "https://test.example.com",
            "AGENT_PUBLIC_KEY": "dGVzdA==",
            "WAKE_EP_INVOKE_METHOD": "zellij",
            "WAKE_EP_ZELLIJ_SESSION": "codex",
        }
        with patch.dict("os.environ", env, clear=True):
            config = load_config_from_env()
        assert config.wake_endpoint.zellij_session == "codex"
        assert config.wake_endpoint.invoke_method == "zellij"

    def test_zellij_endpoint_disabled_skips_validation(self) -> None:
        """Disabled wake endpoint with method=zellij does not require session."""
        from src.server.config import load_config_from_env

        env = {
            "AGENT_ID": "test",
            "AGENT_ENDPOINT": "https://test.example.com",
            "AGENT_PUBLIC_KEY": "dGVzdA==",
            "WAKE_EP_ENABLED": "false",
            "WAKE_EP_INVOKE_METHOD": "zellij",
            "WAKE_EP_ZELLIJ_SESSION": "",
        }
        with patch.dict("os.environ", env, clear=True):
            # Should not raise even with empty zellij_session, because
            # endpoint is disabled
            config = load_config_from_env()
        assert config.wake_endpoint.enabled is False
        assert config.wake_endpoint.invoke_method == "zellij"

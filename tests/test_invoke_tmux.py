"""Tests for the tmux invoke method (subprocess-based, no SDK)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.server.config import WakeEndpointConfig
from src.server.invoke_tmux import TmuxInvokeConfig, _format_notification, invoke_tmux
from src.server.invoker import AgentInvoker


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
    return proc


# ---------------------------------------------------------------------------
# Unit tests: TmuxInvokeConfig
# ---------------------------------------------------------------------------


class TestTmuxInvokeConfig:
    def test_requires_tmux_target(self) -> None:
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        assert cfg.tmux_target == "main:0"

    def test_frozen(self) -> None:
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with pytest.raises(AttributeError):
            cfg.tmux_target = "other"  # type: ignore[misc]


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
# Unit tests: invoke_tmux (two separate exec calls)
# ---------------------------------------------------------------------------


class TestInvokeTmux:
    @pytest.mark.asyncio
    async def test_calls_tmux_send_keys_two_step(self) -> None:
        """Verifies two separate create_subprocess_exec calls."""
        text_proc = _mock_process(returncode=0)
        enter_proc = _mock_process(returncode=0)
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with patch(
            "src.server.invoke_tmux.asyncio.create_subprocess_exec",
            side_effect=[text_proc, enter_proc],
        ) as mock_exec, patch(
            "src.server.invoke_tmux.asyncio.sleep", new_callable=AsyncMock,
        ) as mock_sleep:
            await invoke_tmux(_wake_payload(), cfg)

        assert mock_exec.call_count == 2
        # First call sends the notification text
        text_call = mock_exec.call_args_list[0]
        assert text_call[0][0] == "tmux"
        assert text_call[0][1] == "send-keys"
        assert text_call[0][2] == "-t"
        assert text_call[0][3] == "main:0"
        assert "sender-agent-123" in text_call[0][4]
        # Second call sends C-m (Enter)
        enter_call = mock_exec.call_args_list[1]
        assert enter_call[0] == ("tmux", "send-keys", "-t", "main:0", "C-m")
        # Sleep between the two calls
        mock_sleep.assert_called_once_with(0.5)

    @pytest.mark.asyncio
    async def test_returns_none(self) -> None:
        """invoke_tmux returns None (no session_id)."""
        proc = _mock_process(returncode=0)
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with patch(
            "src.server.invoke_tmux.asyncio.create_subprocess_exec",
            side_effect=[proc, _mock_process(returncode=0)],
        ), patch("src.server.invoke_tmux.asyncio.sleep", new_callable=AsyncMock):
            result = await invoke_tmux(_wake_payload(), cfg)
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_on_text_send_failure(self) -> None:
        """Non-zero exit from the first send-keys (text) raises RuntimeError."""
        text_proc = _mock_process(
            returncode=1, stderr=b"session not found: main:0",
        )
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with patch(
            "src.server.invoke_tmux.asyncio.create_subprocess_exec",
            side_effect=[text_proc],
        ):
            with pytest.raises(RuntimeError, match="tmux send-keys failed"):
                await invoke_tmux(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_raises_on_enter_send_failure(self) -> None:
        """Non-zero exit from the second send-keys (C-m) raises RuntimeError."""
        text_proc = _mock_process(returncode=0)
        enter_proc = _mock_process(returncode=1, stderr=b"no server running")
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with patch(
            "src.server.invoke_tmux.asyncio.create_subprocess_exec",
            side_effect=[text_proc, enter_proc],
        ), patch("src.server.invoke_tmux.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="no server running"):
                await invoke_tmux(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_error_message_includes_stderr(self) -> None:
        """RuntimeError includes stderr content from the failing call."""
        text_proc = _mock_process(returncode=1, stderr=b"no server running")
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with patch(
            "src.server.invoke_tmux.asyncio.create_subprocess_exec",
            side_effect=[text_proc],
        ):
            with pytest.raises(RuntimeError, match="no server running"):
                await invoke_tmux(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_custom_target(self) -> None:
        """Tmux target from config is passed to both send-keys calls."""
        text_proc = _mock_process(returncode=0)
        enter_proc = _mock_process(returncode=0)
        cfg = TmuxInvokeConfig(tmux_target="orchestrator:1.2")
        with patch(
            "src.server.invoke_tmux.asyncio.create_subprocess_exec",
            side_effect=[text_proc, enter_proc],
        ) as mock_exec, patch(
            "src.server.invoke_tmux.asyncio.sleep", new_callable=AsyncMock,
        ):
            await invoke_tmux(_wake_payload(), cfg)

        # Both calls use the custom target
        text_call = mock_exec.call_args_list[0]
        assert text_call[0][3] == "orchestrator:1.2"
        enter_call = mock_exec.call_args_list[1]
        assert enter_call[0][3] == "orchestrator:1.2"

    @pytest.mark.asyncio
    async def test_uses_exec_not_shell(self) -> None:
        """Verifies create_subprocess_exec is used, not create_subprocess_shell."""
        text_proc = _mock_process(returncode=0)
        enter_proc = _mock_process(returncode=0)
        cfg = TmuxInvokeConfig(tmux_target="nexus")
        with patch(
            "src.server.invoke_tmux.asyncio.create_subprocess_exec",
            side_effect=[text_proc, enter_proc],
        ) as mock_exec, patch(
            "src.server.invoke_tmux.asyncio.sleep", new_callable=AsyncMock,
        ), patch(
            "src.server.invoke_tmux.asyncio.create_subprocess_shell",
        ) as mock_shell:
            await invoke_tmux(_wake_payload(), cfg)

        assert mock_exec.call_count == 2
        mock_shell.assert_not_called()

    @pytest.mark.asyncio
    async def test_sleep_between_calls(self) -> None:
        """Confirms asyncio.sleep(0.5) is called between the two exec calls."""
        text_proc = _mock_process(returncode=0)
        enter_proc = _mock_process(returncode=0)
        cfg = TmuxInvokeConfig(tmux_target="nexus")
        call_order: list[str] = []

        async def track_exec(*args: object, **kwargs: object) -> MagicMock:
            call_order.append("exec")
            if len(call_order) == 1:
                return text_proc
            return enter_proc

        async def track_sleep(seconds: float) -> None:
            call_order.append(f"sleep:{seconds}")

        with patch(
            "src.server.invoke_tmux.asyncio.create_subprocess_exec",
            side_effect=track_exec,
        ), patch(
            "src.server.invoke_tmux.asyncio.sleep",
            side_effect=track_sleep,
        ):
            await invoke_tmux(_wake_payload(), cfg)

        assert call_order == ["exec", "sleep:0.5", "exec"]


# ---------------------------------------------------------------------------
# Unit tests: AgentInvoker with tmux method
# ---------------------------------------------------------------------------


class TestAgentInvokerTmux:
    def test_tmux_method_accepted(self) -> None:
        """Tmux method is accepted (no SDK required)."""
        tmux_cfg = TmuxInvokeConfig(tmux_target="main:0")
        invoker = AgentInvoker(
            method="tmux", target="", tmux_config=tmux_cfg,
        )
        assert invoker.method == "tmux"

    def test_tmux_rejects_missing_config(self) -> None:
        """Tmux method raises if tmux_config is not provided."""
        with pytest.raises(ValueError, match="tmux_config required"):
            AgentInvoker(method="tmux", target="")

    def test_tmux_allows_empty_target(self) -> None:
        """Tmux method does not require a target (uses tmux_config instead)."""
        tmux_cfg = TmuxInvokeConfig(tmux_target="main:0")
        invoker = AgentInvoker(
            method="tmux", target="", tmux_config=tmux_cfg,
        )
        assert invoker.method == "tmux"

    @pytest.mark.asyncio
    async def test_tmux_invoke_calls_invoke_tmux(self) -> None:
        """AgentInvoker.invoke delegates to invoke_tmux."""
        tmux_cfg = TmuxInvokeConfig(tmux_target="main:0")
        invoker = AgentInvoker(
            method="tmux", target="", tmux_config=tmux_cfg,
        )
        with patch(
            "src.server.invoke_tmux.invoke_tmux", new_callable=AsyncMock,
        ) as mock:
            result = await invoker.invoke(_wake_payload())
        mock.assert_called_once_with(_wake_payload(), tmux_cfg)
        assert result is None


# ---------------------------------------------------------------------------
# Unit tests: WakeEndpointConfig tmux_target field
# ---------------------------------------------------------------------------


class TestWakeEndpointConfigTmux:
    def test_tmux_target_default_empty(self) -> None:
        cfg = WakeEndpointConfig()
        assert cfg.tmux_target == ""

    def test_tmux_target_custom(self) -> None:
        cfg = WakeEndpointConfig(
            enabled=True,
            invoke_method="tmux",
            tmux_target="main:0",
        )
        assert cfg.tmux_target == "main:0"
        assert cfg.invoke_method == "tmux"


# ---------------------------------------------------------------------------
# Unit tests: config validation for tmux method
# ---------------------------------------------------------------------------


class TestConfigTmuxValidation:
    def test_missing_tmux_target_raises(self) -> None:
        """load_config_from_env raises if tmux method lacks WAKE_EP_TMUX_TARGET."""
        from src.server.config import load_config_from_env

        env = {
            "AGENT_ID": "test",
            "AGENT_ENDPOINT": "https://test.example.com",
            "AGENT_PUBLIC_KEY": "dGVzdA==",
            "WAKE_EP_INVOKE_METHOD": "tmux",
            "WAKE_EP_TMUX_TARGET": "",
        }
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValueError, match="WAKE_EP_TMUX_TARGET"):
                load_config_from_env()

    def test_tmux_target_set_succeeds(self) -> None:
        """load_config_from_env succeeds when tmux_target is set."""
        from src.server.config import load_config_from_env

        env = {
            "AGENT_ID": "test",
            "AGENT_ENDPOINT": "https://test.example.com",
            "AGENT_PUBLIC_KEY": "dGVzdA==",
            "WAKE_EP_INVOKE_METHOD": "tmux",
            "WAKE_EP_TMUX_TARGET": "main:0",
        }
        with patch.dict("os.environ", env, clear=True):
            config = load_config_from_env()
        assert config.wake_endpoint.tmux_target == "main:0"
        assert config.wake_endpoint.invoke_method == "tmux"

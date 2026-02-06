"""Tests for the tmux invoke method (subprocess-based, no SDK)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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
# Unit tests: invoke_tmux (subprocess shell)
# ---------------------------------------------------------------------------


class TestInvokeTmux:
    @pytest.mark.asyncio
    async def test_calls_tmux_send_keys_two_step(self) -> None:
        """Verifies the two-step tmux send-keys shell command."""
        proc = _mock_process(returncode=0)
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with patch("src.server.invoke_tmux.asyncio.create_subprocess_shell",
                    return_value=proc) as mock_shell:
            await invoke_tmux(_wake_payload(), cfg)

        mock_shell.assert_called_once()
        cmd = mock_shell.call_args[0][0]
        # Must contain two separate send-keys calls with sleep between
        assert "tmux send-keys -t main:0" in cmd
        assert "sleep 0.3" in cmd
        assert "tmux send-keys -t main:0 C-m" in cmd
        assert "sender-agent-123" in cmd

    @pytest.mark.asyncio
    async def test_returns_none(self) -> None:
        """invoke_tmux returns None (no session_id)."""
        proc = _mock_process(returncode=0)
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with patch("src.server.invoke_tmux.asyncio.create_subprocess_shell",
                    return_value=proc):
            result = await invoke_tmux(_wake_payload(), cfg)
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_on_nonzero_exit(self) -> None:
        """Non-zero exit code from tmux raises RuntimeError."""
        proc = _mock_process(returncode=1, stderr=b"session not found: main:0")
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with patch("src.server.invoke_tmux.asyncio.create_subprocess_shell",
                    return_value=proc):
            with pytest.raises(RuntimeError, match="tmux send-keys failed"):
                await invoke_tmux(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_error_message_includes_stderr(self) -> None:
        """RuntimeError includes stderr content."""
        proc = _mock_process(returncode=1, stderr=b"no server running")
        cfg = TmuxInvokeConfig(tmux_target="main:0")
        with patch("src.server.invoke_tmux.asyncio.create_subprocess_shell",
                    return_value=proc):
            with pytest.raises(RuntimeError, match="no server running"):
                await invoke_tmux(_wake_payload(), cfg)

    @pytest.mark.asyncio
    async def test_custom_target(self) -> None:
        """Tmux target from config is passed to send-keys."""
        proc = _mock_process(returncode=0)
        cfg = TmuxInvokeConfig(tmux_target="orchestrator:1.2")
        with patch("src.server.invoke_tmux.asyncio.create_subprocess_shell",
                    return_value=proc) as mock_shell:
            await invoke_tmux(_wake_payload(), cfg)

        cmd = mock_shell.call_args[0][0]
        assert "tmux send-keys -t orchestrator:1.2" in cmd

    @pytest.mark.asyncio
    async def test_command_uses_shell_chaining(self) -> None:
        """Verifies the command chains with && for reliability."""
        proc = _mock_process(returncode=0)
        cfg = TmuxInvokeConfig(tmux_target="nexus")
        with patch("src.server.invoke_tmux.asyncio.create_subprocess_shell",
                    return_value=proc) as mock_shell:
            await invoke_tmux(_wake_payload(), cfg)

        cmd = mock_shell.call_args[0][0]
        parts = cmd.split(" && ")
        assert len(parts) == 3
        assert parts[0].startswith("tmux send-keys -t nexus")
        assert parts[1].strip() == "sleep 0.3"
        assert parts[2].strip() == "tmux send-keys -t nexus C-m"


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

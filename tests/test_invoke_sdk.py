"""Tests for the Claude Agent SDK invoke method."""
import sys
from pathlib import Path
from types import ModuleType
from typing import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

from src.server.config import WakeEndpointConfig
from src.server.invoke_sdk import SdkInvokeConfig, _build_prompt, invoke_sdk
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


class FakeResultMessage:
    """Shared fake ResultMessage used by all fake query generators."""

    def __init__(
        self,
        session_id: str = "test-session-abc",
        is_error: bool = False,
    ) -> None:
        self.session_id = session_id
        self.is_error = is_error
        self.subtype = "error" if is_error else "success"
        self.duration_ms = 1000
        self.duration_api_ms = 800
        self.num_turns = 1
        self.total_cost_usd = 0.01
        self.usage = {}
        self.result = "Done"


def _make_fake_sdk() -> ModuleType:
    """Create a fake claude_agent_sdk module for testing.

    Uses the shared FakeResultMessage class so that isinstance checks
    work correctly inside invoke_sdk.
    """
    mod = ModuleType("claude_agent_sdk")
    mod.ClaudeAgentOptions = MagicMock  # type: ignore[attr-defined]
    mod.ResultMessage = FakeResultMessage  # type: ignore[attr-defined]
    return mod


async def _fake_query_success(**kwargs) -> AsyncIterator:  # type: ignore[type-arg]
    """Async generator that yields a successful ResultMessage."""
    yield FakeResultMessage(session_id="session-xyz-123")


async def _fake_query_error(**kwargs) -> AsyncIterator:  # type: ignore[type-arg]
    """Async generator that yields an error ResultMessage."""
    yield FakeResultMessage(session_id="session-err-456", is_error=True)


async def _fake_query_empty(**kwargs) -> AsyncIterator:  # type: ignore[type-arg]
    """Async generator that yields no ResultMessage."""
    return
    yield  # noqa: unreachable -- makes this an async generator


async def _fake_query_raises(**kwargs) -> AsyncIterator:  # type: ignore[type-arg]
    """Async generator that raises an exception."""
    raise ConnectionError("SDK connection failed")
    yield  # noqa: unreachable -- makes this an async generator


# ---------------------------------------------------------------------------
# Unit tests: SdkInvokeConfig
# ---------------------------------------------------------------------------


class TestSdkInvokeConfig:
    def test_defaults(self) -> None:
        cfg = SdkInvokeConfig()
        assert cfg.cwd == "/root/nexus"
        assert cfg.permission_mode == "acceptEdits"
        assert cfg.max_turns is None
        assert "Read" in cfg.allowed_tools
        assert "Task" in cfg.allowed_tools
        assert cfg.model is None

    def test_custom_values(self) -> None:
        cfg = SdkInvokeConfig(
            cwd="/tmp/custom",
            permission_mode="plan",
            max_turns=5,
            allowed_tools=["Read", "Write"],
            model="claude-sonnet-4-20250514",
        )
        assert cfg.cwd == "/tmp/custom"
        assert cfg.permission_mode == "plan"
        assert cfg.max_turns == 5
        assert cfg.allowed_tools == ["Read", "Write"]
        assert cfg.model == "claude-sonnet-4-20250514"

    def test_frozen(self) -> None:
        cfg = SdkInvokeConfig()
        with pytest.raises(AttributeError):
            cfg.cwd = "/other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Unit tests: _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_includes_sender_and_ids(self) -> None:
        prompt = _build_prompt(_wake_payload())
        assert "sender-agent-123" in prompt
        assert "550e8400" in prompt
        assert "660e8400" in prompt

    def test_defaults_for_missing_fields(self) -> None:
        prompt = _build_prompt({})
        assert "unknown" in prompt


# ---------------------------------------------------------------------------
# Unit tests: AgentInvoker with sdk method
# ---------------------------------------------------------------------------


class TestAgentInvokerSdk:
    def test_sdk_method_accepted(self) -> None:
        """SDK method is accepted when the package is available."""
        fake_sdk = _make_fake_sdk()
        with patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk}):
            invoker = AgentInvoker(method="sdk", target="")
            assert invoker.method == "sdk"

    def test_sdk_allows_empty_target(self) -> None:
        """SDK method does not require a target."""
        fake_sdk = _make_fake_sdk()
        with patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk}):
            invoker = AgentInvoker(method="sdk", target="")
            assert invoker.method == "sdk"

    def test_sdk_rejects_when_not_installed(self) -> None:
        """SDK method raises if claude-agent-sdk is not importable."""
        with patch.dict(sys.modules, {"claude_agent_sdk": None}):
            with pytest.raises(RuntimeError, match="claude-agent-sdk"):
                AgentInvoker(method="sdk", target="")

    def test_unknown_method_still_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown invocation method"):
            AgentInvoker(method="magic", target="")

    def test_sdk_config_passed_through(self) -> None:
        """Custom SdkInvokeConfig is stored on the invoker."""
        fake_sdk = _make_fake_sdk()
        custom_cfg = SdkInvokeConfig(cwd="/custom", max_turns=3)
        with patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk}):
            invoker = AgentInvoker(
                method="sdk", target="", sdk_config=custom_cfg,
            )
            assert invoker._sdk_config.cwd == "/custom"
            assert invoker._sdk_config.max_turns == 3


# ---------------------------------------------------------------------------
# Unit tests: invoke_sdk function
# ---------------------------------------------------------------------------


class TestInvokeSdk:
    @pytest.mark.asyncio
    async def test_returns_session_id_on_success(self) -> None:
        fake_sdk = _make_fake_sdk()
        fake_sdk.query = _fake_query_success  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk}):
            result = await invoke_sdk(_wake_payload(), SdkInvokeConfig())
        assert result == "session-xyz-123"

    @pytest.mark.asyncio
    async def test_returns_session_id_on_error_result(self) -> None:
        fake_sdk = _make_fake_sdk()
        fake_sdk.query = _fake_query_error  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk}):
            result = await invoke_sdk(_wake_payload(), SdkInvokeConfig())
        assert result == "session-err-456"

    @pytest.mark.asyncio
    async def test_raises_on_no_result_message(self) -> None:
        fake_sdk = _make_fake_sdk()
        fake_sdk.query = _fake_query_empty  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk}):
            with pytest.raises(RuntimeError, match="without a ResultMessage"):
                await invoke_sdk(_wake_payload(), SdkInvokeConfig())

    @pytest.mark.asyncio
    async def test_propagates_sdk_exception(self) -> None:
        fake_sdk = _make_fake_sdk()
        fake_sdk.query = _fake_query_raises  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk}):
            with pytest.raises(ConnectionError, match="SDK connection failed"):
                await invoke_sdk(_wake_payload(), SdkInvokeConfig())

    @pytest.mark.asyncio
    async def test_uses_custom_config(self) -> None:
        """Verify custom config is passed to ClaudeAgentOptions."""
        fake_sdk = _make_fake_sdk()
        captured_kwargs: dict = {}

        async def capturing_query(**kwargs) -> AsyncIterator:  # type: ignore[type-arg]
            captured_kwargs.update(kwargs)
            yield FakeResultMessage(session_id="cap-session")

        fake_sdk.query = capturing_query  # type: ignore[attr-defined]
        cfg = SdkInvokeConfig(cwd="/my/project", max_turns=7)
        with patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk}):
            result = await invoke_sdk(_wake_payload(), cfg)
        assert result == "cap-session"
        # The options object was constructed (MagicMock), verify query was called
        assert "prompt" in captured_kwargs


# ---------------------------------------------------------------------------
# Unit tests: WakeEndpointConfig SDK fields
# ---------------------------------------------------------------------------


class TestWakeEndpointConfigSdk:
    def test_sdk_defaults(self) -> None:
        cfg = WakeEndpointConfig()
        assert cfg.sdk_cwd == "/root/nexus"
        assert cfg.sdk_permission_mode == "acceptEdits"
        assert cfg.sdk_max_turns is None
        assert cfg.sdk_model is None

    def test_sdk_custom_values(self) -> None:
        cfg = WakeEndpointConfig(
            enabled=True,
            invoke_method="sdk",
            sdk_cwd="/custom/path",
            sdk_permission_mode="plan",
            sdk_max_turns=10,
            sdk_model="claude-sonnet-4-20250514",
        )
        assert cfg.sdk_cwd == "/custom/path"
        assert cfg.sdk_permission_mode == "plan"
        assert cfg.sdk_max_turns == 10
        assert cfg.sdk_model == "claude-sonnet-4-20250514"

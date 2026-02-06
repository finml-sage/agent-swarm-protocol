"""Pluggable agent invocation strategies for the wake endpoint."""
import asyncio
import logging
from typing import Optional

from src.server.invoke_sdk import SdkInvokeConfig
from src.server.invoke_tmux import TmuxInvokeConfig

logger = logging.getLogger(__name__)

_VALID_METHODS = ("subprocess", "webhook", "noop", "sdk", "tmux")
_METHODS_REQUIRING_TARGET = ("subprocess", "webhook")


class AgentInvoker:
    """Pluggable agent invocation.

    The invocation method is determined by ``method``:
      - ``"subprocess"``: launch a command (default, generic)
      - ``"webhook"``: POST to a URL
      - ``"sdk"``: invoke via the Claude Agent SDK
      - ``"tmux"``: send notification into a tmux session via send-keys
      - ``"noop"``: do nothing (for testing / dry-run)
    """

    def __init__(
        self,
        method: str,
        target: str,
        sdk_config: Optional[SdkInvokeConfig] = None,
        tmux_config: Optional[TmuxInvokeConfig] = None,
    ) -> None:
        if method not in _VALID_METHODS:
            raise ValueError(
                f"Unknown invocation method '{method}'. "
                f"Expected one of: {', '.join(repr(m) for m in _VALID_METHODS)}."
            )
        if method in _METHODS_REQUIRING_TARGET and not target:
            raise ValueError(f"Invocation target required for method '{method}'")
        if method == "sdk":
            _assert_sdk_available()
        if method == "tmux":
            if tmux_config is None:
                raise ValueError(
                    "tmux_config required for method 'tmux'. "
                    "Set WAKE_EP_TMUX_TARGET to a tmux session target."
                )
        self._method = method
        self._target = target
        self._sdk_config = sdk_config or SdkInvokeConfig()
        self._tmux_config = tmux_config

    @property
    def method(self) -> str:
        return self._method

    async def invoke(
        self, payload: dict, resume: Optional[str] = None
    ) -> Optional[str]:
        """Invoke the agent with the given wake payload.

        Args:
            payload: The wake payload with message metadata.
            resume: Previous SDK session_id to continue, or None.

        Returns:
            The SDK session_id when method is 'sdk', None otherwise.
        """
        if self._method == "noop":
            logger.info("noop invoker: skipping invocation")
            return None
        if self._method == "subprocess":
            await self._invoke_subprocess(payload)
            return None
        if self._method == "webhook":
            await self._invoke_webhook(payload)
            return None
        if self._method == "sdk":
            from src.server.invoke_sdk import invoke_sdk

            return await invoke_sdk(payload, self._sdk_config, resume=resume)
        if self._method == "tmux":
            await self._invoke_tmux(payload)
            return None
        return None

    async def _invoke_subprocess(self, payload: dict) -> None:
        """Launch agent as a subprocess."""
        cmd = self._target.format(**payload)
        logger.info("Invoking agent via subprocess: %s", cmd)
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Fire-and-forget: don't await completion (agent may run long)
        logger.info("Agent subprocess started, pid=%s", process.pid)

    async def _invoke_webhook(self, payload: dict) -> None:
        """POST to a webhook URL to trigger the agent."""
        import httpx

        logger.info("Invoking agent via webhook: %s", self._target)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(self._target, json=payload)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Webhook {self._target} returned {response.status_code}"
                )

    async def _invoke_tmux(self, payload: dict) -> None:
        """Send notification into a tmux session via send-keys."""
        from src.server.invoke_tmux import invoke_tmux

        if self._tmux_config is None:
            raise RuntimeError("tmux_config is None but method is 'tmux'")

        await invoke_tmux(payload, self._tmux_config)


def _assert_sdk_available() -> None:
    """Raise if the claude-agent-sdk package is not installed."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "The 'sdk' invoke method requires the claude-agent-sdk package. "
            "Install it with: pip install claude-agent-sdk "
            "or pip install agent-swarm-protocol[wake]"
        ) from None

"""Pluggable agent invocation strategies for the wake endpoint."""
import asyncio
import logging
from typing import Optional

from src.server.invoke_sdk import SdkInvokeConfig

logger = logging.getLogger(__name__)

_VALID_METHODS = ("subprocess", "webhook", "noop", "sdk")
_METHODS_REQUIRING_TARGET = ("subprocess", "webhook")


class AgentInvoker:
    """Pluggable agent invocation.

    The invocation method is determined by ``method``:
      - ``"subprocess"``: launch a command (default, generic)
      - ``"webhook"``: POST to a URL
      - ``"sdk"``: invoke via the Claude Agent SDK
      - ``"noop"``: do nothing (for testing / dry-run)
    """

    def __init__(
        self,
        method: str,
        target: str,
        sdk_config: Optional[SdkInvokeConfig] = None,
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
        self._method = method
        self._target = target
        self._sdk_config = sdk_config or SdkInvokeConfig()

    @property
    def method(self) -> str:
        return self._method

    async def invoke(self, payload: dict) -> Optional[str]:
        """Invoke the agent with the given wake payload.

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

            return await invoke_sdk(payload, self._sdk_config)
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

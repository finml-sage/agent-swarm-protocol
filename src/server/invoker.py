"""Pluggable agent invocation strategies for the wake endpoint."""
import asyncio
import logging

logger = logging.getLogger(__name__)


class AgentInvoker:
    """Pluggable agent invocation.

    The invocation method is determined by ``method``:
      - ``"subprocess"``: launch a command (default, generic)
      - ``"webhook"``: POST to a URL
      - ``"noop"``: do nothing (for testing / dry-run)

    Subclass or replace to add deployment-specific methods.
    """

    def __init__(self, method: str, target: str) -> None:
        if method not in ("subprocess", "webhook", "noop"):
            raise ValueError(
                f"Unknown invocation method '{method}'. "
                "Expected 'subprocess', 'webhook', or 'noop'."
            )
        if method != "noop" and not target:
            raise ValueError(f"Invocation target required for method '{method}'")
        self._method = method
        self._target = target

    @property
    def method(self) -> str:
        return self._method

    async def invoke(self, payload: dict) -> None:
        """Invoke the agent with the given wake payload."""
        if self._method == "noop":
            logger.info("noop invoker: skipping invocation")
            return
        if self._method == "subprocess":
            await self._invoke_subprocess(payload)
            return
        if self._method == "webhook":
            await self._invoke_webhook(payload)
            return

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

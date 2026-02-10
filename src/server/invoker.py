"""Pluggable agent invocation strategies for the wake endpoint."""
import logging
from typing import Optional

from src.server.invoke_tmux import TmuxInvokeConfig

logger = logging.getLogger(__name__)

_VALID_METHODS = ("noop", "tmux")


class AgentInvoker:
    """Pluggable agent invocation.

    The invocation method is determined by ``method``:
      - ``"tmux"``: send notification into a tmux session via send-keys
      - ``"noop"``: do nothing (for testing / dry-run)
    """

    def __init__(
        self,
        method: str,
        tmux_config: Optional[TmuxInvokeConfig] = None,
    ) -> None:
        if method not in _VALID_METHODS:
            raise ValueError(
                f"Unknown invocation method '{method}'. "
                f"Expected one of: {', '.join(repr(m) for m in _VALID_METHODS)}."
            )
        if method == "tmux":
            if tmux_config is None:
                raise ValueError(
                    "tmux_config required for method 'tmux'. "
                    "Set WAKE_EP_TMUX_TARGET to a tmux session target."
                )
        self._method = method
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
            resume: Reserved for future use (ignored by tmux/noop).

        Returns:
            None for both tmux and noop methods.
        """
        if self._method == "noop":
            logger.info("noop invoker: skipping invocation")
            return None
        if self._method == "tmux":
            await self._invoke_tmux(payload)
            return None
        return None

    async def _invoke_tmux(self, payload: dict) -> None:
        """Send notification into a tmux session via send-keys."""
        from src.server.invoke_tmux import invoke_tmux

        if self._tmux_config is None:
            raise RuntimeError("tmux_config is None but method is 'tmux'")

        await invoke_tmux(payload, self._tmux_config)

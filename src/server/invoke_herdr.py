"""Herdr invocation strategy.

Delivers the wake notification to a coding agent running in a Herdr pane via
``herdr agent prompt <target> <text>``.  Herdr sends the text and Enter as one
ordered submission, honours the pane's bracketed-paste mode, and refuses a
target that does not currently host a recognised agent -- so a wake never
lands in a bare shell.
"""
import asyncio
import logging
from dataclasses import dataclass

from src.server.invoke_tmux import _format_notification

logger = logging.getLogger(__name__)

# Match invoke_zellij: 5s subprocess timeout so a stuck herdr CLI call
# cannot wedge the wake lock indefinitely.  Exposed for tests.
_SUBPROCESS_TIMEOUT: float = 5.0


@dataclass(frozen=True)
class HerdrInvokeConfig:
    """Configuration for the herdr invoke method.

    Attributes:
        target: A live Herdr agent name or the pane id hosting the agent
            (e.g. 'sage' or 'w1:p1').
        herdr_bin: Path to the herdr binary (services often lack ~/.local/bin
            on PATH).
    """

    target: str
    herdr_bin: str = "herdr"


async def invoke_herdr(payload: dict, config: HerdrInvokeConfig) -> None:
    """Send a notification to a Herdr-hosted agent.

    Raises:
        RuntimeError: If herdr exits non-zero (no agent at the target, agent
            blocked on a dialog, server unreachable) or does not finish
            within 5s.
    """
    notification = _format_notification(payload)
    logger.info("Sending herdr notification to target=%s", config.target)

    proc = await asyncio.create_subprocess_exec(
        config.herdr_bin, "agent", "prompt", config.target, notification,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise RuntimeError(
            f"herdr agent prompt timed out after {_SUBPROCESS_TIMEOUT}s "
            f"(target={config.target!r})"
        )
    if proc.returncode != 0:
        detail = (stderr or stdout or b"").decode().strip() or "unknown error"
        raise RuntimeError(
            f"herdr agent prompt failed (exit {proc.returncode}): {detail}"
        )

    logger.info("Herdr notification sent successfully")

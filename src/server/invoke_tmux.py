"""Tmux invocation strategy.

Sends a notification string into a running tmux session via
``tmux send-keys``.  This is a simple IPC mechanism -- no SDK,
no AI relay, just format a string and deliver it.
"""
import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TmuxInvokeConfig:
    """Configuration for the tmux invoke method.

    Attributes:
        tmux_target: The tmux session/window/pane target (e.g. 'main:0').
    """

    tmux_target: str


def _format_notification(payload: dict) -> str:
    """Build a one-line notification string from a wake payload."""
    sender = payload.get("sender_id", "unknown")
    return f"Wake: new message from {sender}. Read and process."


async def invoke_tmux(payload: dict, config: TmuxInvokeConfig) -> None:
    """Send a notification into a tmux session via ``tmux send-keys``.

    Uses two separate send-keys calls with a small delay between them.
    The first call sends the text, the second sends C-m (Enter).
    A single combined call does not reliably deliver the Enter key.

    Args:
        payload: The wake payload with message metadata.
        config: Tmux configuration (session target).

    Raises:
        RuntimeError: If the tmux command fails (non-zero exit code).
    """
    notification = _format_notification(payload)
    logger.info(
        "Sending tmux notification to target=%s", config.tmux_target,
    )

    target = config.tmux_target
    cmd = (
        f"tmux send-keys -t {target} '{notification}'"
        f" && sleep 0.3"
        f" && tmux send-keys -t {target} C-m"
    )
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        err_msg = stderr.decode().strip() if stderr else "unknown error"
        raise RuntimeError(
            f"tmux send-keys failed (exit {process.returncode}): {err_msg}"
        )
    logger.info("Tmux notification sent successfully")

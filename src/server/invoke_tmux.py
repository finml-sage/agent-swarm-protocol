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

    Uses two separate ``create_subprocess_exec`` calls with a sleep between
    them.  The first sends the text, the second sends C-m (Enter).  A single
    combined call does not reliably deliver the Enter key.

    Args:
        payload: The wake payload with message metadata.
        config: Tmux configuration (session target).

    Raises:
        RuntimeError: If either tmux command fails (non-zero exit code).
    """
    notification = _format_notification(payload)
    logger.info(
        "Sending tmux notification to target=%s", config.tmux_target,
    )

    target = config.tmux_target

    # Step 1: send the text into the tmux pane
    text_proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", target, notification,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, text_stderr = await text_proc.communicate()
    if text_proc.returncode != 0:
        err_msg = text_stderr.decode().strip() if text_stderr else "unknown error"
        raise RuntimeError(
            f"tmux send-keys failed (exit {text_proc.returncode}): {err_msg}"
        )

    # Step 2: wait for tmux to process the text
    await asyncio.sleep(0.5)

    # Step 3: send Enter (C-m)
    enter_proc = await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", target, "C-m",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, enter_stderr = await enter_proc.communicate()
    if enter_proc.returncode != 0:
        err_msg = enter_stderr.decode().strip() if enter_stderr else "unknown error"
        raise RuntimeError(
            f"tmux send-keys failed (exit {enter_proc.returncode}): {err_msg}"
        )

    logger.info("Tmux notification sent successfully")

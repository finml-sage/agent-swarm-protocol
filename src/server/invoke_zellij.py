"""Zellij invocation strategy.

Sends a notification string into a running zellij session via
``zellij action write-chars`` followed by ``zellij action send-keys
Enter``.  This is the zellij peer to ``invoke_tmux``: a simple IPC
mechanism -- no SDK, no AI relay, just format a string and deliver it
into the focused pane of the named zellij session.

argv shape (verified against zellij 0.45.0
``zellij-utils/src/cli.rs::CliAction``):

  * write-chars: ``zellij --session SESSION action write-chars TEXT``
  * send-keys:   ``zellij --session SESSION action send-keys "Enter"``

The forcing-function semantics mirror tmux ``send-keys``: bytes go
into the focused pane's PTY master via the same code path real
keyboard input takes.  Empirical TUI-layer verification under Codex
CLI is deferred to Phase 0.C of the web-codex-user-ideoon project.
"""

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Match invoke_tmux: 5s per-subprocess timeout so a stuck zellij CLI
# call cannot wedge the wake lock indefinitely.  Exposed for tests.
_SUBPROCESS_TIMEOUT: float = 5.0


@dataclass(frozen=True)
class ZellijInvokeConfig:
    """Configuration for the zellij invoke method.

    Attributes:
        zellij_session: The zellij session name (passed via ``--session``).
            The pane is the focused pane of that session; per-pane
            targeting via ``--pane-id`` is not exposed here.
    """

    zellij_session: str


def _format_notification(payload: dict) -> str:
    """Build a one-line notification string from a wake payload.

    Identical shape to ``invoke_tmux._format_notification`` so both
    invokers produce the same on-screen text for the same payload.
    """
    sender = payload.get("sender_id", "unknown")
    return f"Wake: new message from {sender}. Read and process."


async def _run_zellij(args: tuple[str, ...], session: str, step: str) -> None:
    """Run a single ``zellij --session ... action ...`` subprocess.

    Wraps ``communicate()`` in ``asyncio.wait_for`` so a hung zellij
    CLI invocation cannot hold the wake lock forever.  On non-zero
    exit OR timeout, raises ``RuntimeError``.

    Args:
        args: positional argv after ``zellij --session SESSION action``.
        session: zellij session name (for the error message only -- the
            session is already in ``args[0]`` upstream).
        step: human-readable step name used in error messages
            (``"write-chars"`` or ``"send-keys"``).
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise RuntimeError(
            f"zellij {step} timed out after {_SUBPROCESS_TIMEOUT}s "
            f"(session={session!r})"
        )
    if proc.returncode != 0:
        err_msg = stderr_bytes.decode().strip() if stderr_bytes else "unknown error"
        raise RuntimeError(f"zellij {step} failed (exit {proc.returncode}): {err_msg}")


async def invoke_zellij(payload: dict, config: ZellijInvokeConfig) -> None:
    """Send a notification into a zellij session.

    Two separate ``create_subprocess_exec`` calls with a 0.5s sleep
    between them.  The first writes the notification text; the second
    submits Enter.  Single-call combined delivery is unreliable (same
    failure mode as tmux), so the two-step pattern is preserved here.

    Args:
        payload: The wake payload with message metadata.
        config: Zellij configuration (session name).

    Raises:
        RuntimeError: If either zellij command fails (non-zero exit
            code, missing binary, or 5s timeout).
    """
    notification = _format_notification(payload)
    logger.info(
        "Sending zellij notification to session=%s",
        config.zellij_session,
    )

    session = config.zellij_session

    # Step 1: write the notification text into the focused pane
    await _run_zellij(
        (
            "zellij",
            "--session",
            session,
            "action",
            "write-chars",
            notification,
        ),
        session=session,
        step="write-chars",
    )

    # Step 2: wait for zellij to process the text (mirror tmux 0.5s)
    await asyncio.sleep(0.5)

    # Step 3: submit Enter via send-keys (key tokens space-separated;
    # "Enter" is the documented spelling per cli.rs::SendKeys)
    await _run_zellij(
        (
            "zellij",
            "--session",
            session,
            "action",
            "send-keys",
            "Enter",
        ),
        session=session,
        step="send-keys",
    )

    logger.info("Zellij notification sent successfully")

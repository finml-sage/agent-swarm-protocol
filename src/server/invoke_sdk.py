"""Claude Agent SDK invocation strategy.

This module isolates the claude-agent-sdk dependency so that the
rest of the server can import ``SdkInvokeConfig`` without requiring
the SDK to be installed.  The actual SDK import happens inside
``invoke_sdk()`` at call time.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SdkInvokeConfig:
    """Configuration for the Claude Agent SDK invoke method.

    Attributes:
        cwd: Working directory for the Claude session.
        permission_mode: Permission mode (e.g. 'acceptEdits').
        max_turns: Maximum conversation turns per invocation.
        allowed_tools: Tool names the agent may use.
        model: Model override (None uses the CLI default).
    """

    cwd: str = "/root/nexus"
    permission_mode: str = "acceptEdits"
    max_turns: Optional[int] = None
    allowed_tools: list[str] = field(
        default_factory=lambda: [
            "Read", "Edit", "Bash", "Glob", "Grep", "Task",
        ]
    )
    model: Optional[str] = None


def _build_prompt(payload: dict) -> str:
    """Build the agent prompt from a wake payload."""
    sender = payload.get("sender_id", "unknown")
    message_id = payload.get("message_id", "unknown")
    swarm_id = payload.get("swarm_id", "unknown")
    return (
        f"Incoming A2A message from {sender} "
        f"(message_id={message_id}, swarm_id={swarm_id}).\n"
        f"Check for new messages and process them."
    )


async def invoke_sdk(
    payload: dict,
    config: SdkInvokeConfig,
    resume: Optional[str] = None,
) -> str:
    """Invoke the agent via the Claude Agent SDK.

    Builds a prompt from the wake payload and calls ``query()``
    with the configured SDK options.  When ``resume`` is provided,
    the SDK continues the existing conversation instead of starting
    a new one.

    The async for loop consumes the full generator without an early
    ``break`` so that the SDK cancel scope exits cleanly in the
    same task that entered it.

    Args:
        payload: The wake payload with message metadata.
        config: SDK invocation configuration.
        resume: Previous session_id to resume, or None for new session.

    Returns:
        The session_id from the ResultMessage for future continuity.

    Raises:
        RuntimeError: If the SDK query completes without a ResultMessage.
    """
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        ResultMessage,
    )

    prompt = _build_prompt(payload)
    options = ClaudeAgentOptions(
        allowed_tools=list(config.allowed_tools),
        permission_mode=config.permission_mode,
        cwd=config.cwd,
        max_turns=config.max_turns,
        model=config.model,
        setting_sources=["project"],
        resume=resume,
    )

    logger.info(
        "Invoking agent via SDK (cwd=%s, sender=%s, resume=%s)",
        config.cwd,
        payload.get("sender_id", "unknown"),
        resume,
    )

    session_id: Optional[str] = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            session_id = message.session_id
            if getattr(message, "is_error", False):
                logger.warning(
                    "SDK invocation completed with error, session=%s",
                    session_id,
                )
            else:
                logger.info(
                    "SDK invocation completed, session=%s", session_id,
                )

    if session_id is None:
        raise RuntimeError("SDK query completed without a ResultMessage")

    return session_id

"""Server configuration."""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os

logger = logging.getLogger(__name__)

_RECOGNISED_BOOL_VALUES = frozenset(
    ("1", "true", "yes", "0", "false", "no")
)


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    endpoint: str
    public_key: str
    protocol_version: str = "0.1.0"
    capabilities: tuple[str, ...] = ("message", "system", "notification")
    name: Optional[str] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class RateLimitConfig:
    messages_per_minute: int = 60
    join_requests_per_hour: int = 10


@dataclass(frozen=True)
class WakeConfig:
    """Configuration for wake trigger behavior.

    Enabled by default.  Set ``WAKE_ENABLED=false`` to disable the
    automatic agent notification when messages arrive.  When disabled
    the trigger is not created and no HTTP calls are made.
    """

    enabled: bool = True
    endpoint: str = "http://localhost:8080/api/wake"
    timeout: float = 5.0


@dataclass(frozen=True)
class WakeEndpointConfig:
    """Configuration for the /api/wake endpoint that receives wake POSTs.

    Enabled by default.  Set ``WAKE_EP_ENABLED=false`` to disable.

    ``invoke_method``: how to start the agent -- 'subprocess', 'webhook',
        'sdk', 'tmux', or 'noop'.
    ``invoke_target``: command template (subprocess) or URL (webhook).
        Not used by sdk/tmux/noop.
    ``secret``: shared secret for X-Wake-Secret header auth. Empty disables auth.
    ``session_file``: path to session state file for duplicate-invocation guard.
    ``session_timeout_minutes``: how long before an active session is considered expired.
    ``sdk_cwd``: working directory for the Claude Agent SDK session.
    ``sdk_permission_mode``: SDK permission mode (e.g. 'acceptEdits').
    ``sdk_max_turns``: maximum conversation turns per SDK invocation.
    ``sdk_model``: model override for SDK invocations (None uses default).
    ``tmux_target``: tmux session/window/pane target for the tmux relay method.
    """

    enabled: bool = True
    invoke_method: str = "noop"
    invoke_target: str = ""
    secret: str = ""
    session_file: str = "/root/.swarm/session.json"
    session_timeout_minutes: int = 30
    sdk_cwd: str = "/root/nexus"
    sdk_permission_mode: str = "acceptEdits"
    sdk_max_turns: Optional[int] = None
    sdk_model: Optional[str] = None
    tmux_target: str = ""


@dataclass(frozen=True)
class ServerConfig:
    agent: AgentConfig
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    queue_max_size: int = 10000
    db_path: Path = field(default_factory=lambda: Path("data/swarm.db"))
    wake: WakeConfig = field(default_factory=WakeConfig)
    wake_endpoint: WakeEndpointConfig = field(default_factory=WakeEndpointConfig)


def _parse_bool(value: str, default: bool) -> bool:
    """Parse a boolean environment variable with explicit default.

    Recognises ``true/1/yes`` and ``false/0/no`` (case-insensitive).
    Returns *default* when the value is empty or unset.
    Logs a warning and returns *default* for unrecognised values
    (e.g. typos like ``ture``).
    """
    if not value:
        return default
    normalised = value.lower()
    if normalised not in _RECOGNISED_BOOL_VALUES:
        logger.warning(
            "Unrecognised boolean value %r, using default %s. "
            "Expected one of: true/1/yes or false/0/no.",
            value,
            default,
        )
        return default
    return normalised in ("1", "true", "yes")


def load_config_from_env() -> ServerConfig:
    agent_id = os.environ.get("AGENT_ID")
    endpoint = os.environ.get("AGENT_ENDPOINT")
    public_key = os.environ.get("AGENT_PUBLIC_KEY")
    missing = []
    if not agent_id:
        missing.append("AGENT_ID")
    if not endpoint:
        missing.append("AGENT_ENDPOINT")
    if not public_key:
        missing.append("AGENT_PUBLIC_KEY")
    if missing:
        raise ValueError(f"Missing: {', '.join(missing)}")

    wake_enabled = _parse_bool(os.environ.get("WAKE_ENABLED", ""), default=True)
    wake_endpoint_url = os.environ.get(
        "WAKE_ENDPOINT", "http://localhost:8080/api/wake"
    )
    if wake_enabled and not wake_endpoint_url:
        raise ValueError("WAKE_ENDPOINT required when WAKE_ENABLED is set")

    wake_ep_enabled = _parse_bool(
        os.environ.get("WAKE_EP_ENABLED", ""), default=True
    )
    wake_ep_secret = os.environ.get("WAKE_EP_SECRET", "")
    if wake_ep_enabled and not wake_ep_secret:
        logger.warning(
            "Wake endpoint enabled with no WAKE_EP_SECRET -- "
            "unauthenticated access. Set WAKE_EP_SECRET or "
            "WAKE_EP_ENABLED=false to silence this warning."
        )

    invoke_method = os.environ.get("WAKE_EP_INVOKE_METHOD", "noop")
    invoke_target = os.environ.get("WAKE_EP_INVOKE_TARGET", "")
    _target_required_methods = ("subprocess", "webhook")
    if wake_ep_enabled and invoke_method in _target_required_methods and not invoke_target:
        raise ValueError(
            "WAKE_EP_INVOKE_TARGET required when WAKE_EP_ENABLED is set "
            f"and method is '{invoke_method}'"
        )

    tmux_target = os.environ.get("WAKE_EP_TMUX_TARGET", "")
    if wake_ep_enabled and invoke_method == "tmux" and not tmux_target:
        raise ValueError(
            "WAKE_EP_TMUX_TARGET required when WAKE_EP_INVOKE_METHOD is 'tmux'. "
            "Set it to a tmux session target (e.g. 'main:0')."
        )

    sdk_max_turns_raw = os.environ.get("WAKE_EP_SDK_MAX_TURNS")
    sdk_max_turns = int(sdk_max_turns_raw) if sdk_max_turns_raw else None

    return ServerConfig(
        agent=AgentConfig(
            agent_id=agent_id,
            endpoint=endpoint,
            public_key=public_key,
            name=os.environ.get("AGENT_NAME"),
            description=os.environ.get("AGENT_DESCRIPTION"),
        ),
        rate_limit=RateLimitConfig(
            messages_per_minute=int(os.environ.get("RATE_LIMIT_MESSAGES_PER_MINUTE", "60")),
            join_requests_per_hour=int(os.environ.get("RATE_LIMIT_JOIN_PER_HOUR", "10")),
        ),
        queue_max_size=int(os.environ.get("QUEUE_MAX_SIZE", "10000")),
        db_path=Path(os.environ.get("DB_PATH", "data/swarm.db")),
        wake=WakeConfig(
            enabled=wake_enabled,
            endpoint=wake_endpoint_url,
            timeout=float(os.environ.get("WAKE_TIMEOUT", "5.0")),
        ),
        wake_endpoint=WakeEndpointConfig(
            enabled=wake_ep_enabled,
            invoke_method=invoke_method,
            invoke_target=invoke_target,
            secret=wake_ep_secret,
            session_file=os.environ.get(
                "WAKE_EP_SESSION_FILE", "/root/.swarm/session.json"
            ),
            session_timeout_minutes=int(
                os.environ.get("WAKE_EP_SESSION_TIMEOUT", "30")
            ),
            sdk_cwd=os.environ.get("WAKE_EP_SDK_CWD", "/root/nexus"),
            sdk_permission_mode=os.environ.get("WAKE_EP_SDK_PERMISSION_MODE", "acceptEdits"),
            sdk_max_turns=sdk_max_turns,
            sdk_model=os.environ.get("WAKE_EP_SDK_MODEL"),
            tmux_target=tmux_target,
        ),
    )

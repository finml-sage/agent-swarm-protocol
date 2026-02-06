"""Server configuration."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os


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

    Set ``enabled=True`` and provide ``endpoint`` to activate automatic
    agent notification when messages arrive.  When disabled the trigger
    is not created and no HTTP calls are made.
    """

    enabled: bool = False
    endpoint: str = ""
    timeout: float = 5.0


@dataclass(frozen=True)
class ServerConfig:
    agent: AgentConfig
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    queue_max_size: int = 10000
    db_path: Path = field(default_factory=lambda: Path("data/swarm.db"))
    wake: WakeConfig = field(default_factory=WakeConfig)


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

    wake_enabled = os.environ.get("WAKE_ENABLED", "").lower() in ("1", "true", "yes")
    wake_endpoint = os.environ.get("WAKE_ENDPOINT", "")
    if wake_enabled and not wake_endpoint:
        raise ValueError("WAKE_ENDPOINT required when WAKE_ENABLED is set")

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
            endpoint=wake_endpoint,
            timeout=float(os.environ.get("WAKE_TIMEOUT", "5.0")),
        ),
    )

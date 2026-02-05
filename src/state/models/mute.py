"""Mute list models."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class MutedAgent:
    agent_id: str
    muted_at: datetime
    reason: Optional[str] = None
    def __post_init__(self) -> None:
        if not self.agent_id: raise ValueError("agent_id cannot be empty")

@dataclass(frozen=True)
class MutedSwarm:
    swarm_id: str
    muted_at: datetime
    reason: Optional[str] = None
    def __post_init__(self) -> None:
        if not self.swarm_id: raise ValueError("swarm_id cannot be empty")

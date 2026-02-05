"""Swarm member models."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class SwarmSettings:
    allow_member_invite: bool = False
    require_approval: bool = False

@dataclass(frozen=True)
class SwarmMember:
    agent_id: str
    endpoint: str
    public_key: str
    joined_at: datetime
    def __post_init__(self) -> None:
        if not self.agent_id: raise ValueError("agent_id cannot be empty")
        if not self.endpoint: raise ValueError("endpoint cannot be empty")
        if not self.endpoint.startswith("https://"): raise ValueError("endpoint must use HTTPS")
        if not self.public_key: raise ValueError("public_key cannot be empty")

@dataclass(frozen=True)
class SwarmMembership:
    swarm_id: str
    name: str
    master: str
    members: tuple[SwarmMember, ...]
    joined_at: datetime
    settings: SwarmSettings = field(default_factory=SwarmSettings)
    nickname: Optional[str] = None
    def __post_init__(self) -> None:
        if not self.swarm_id: raise ValueError("swarm_id cannot be empty")
        if not self.name: raise ValueError("name cannot be empty")
        if len(self.name) > 256: raise ValueError("name cannot exceed 256 characters")
        if not self.master: raise ValueError("master cannot be empty")
        if not self.members: raise ValueError("members cannot be empty")

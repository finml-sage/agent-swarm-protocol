"""Public key models."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class PublicKeyEntry:
    agent_id: str
    public_key: str
    fetched_at: datetime
    endpoint: Optional[str] = None
    def __post_init__(self) -> None:
        if not self.agent_id: raise ValueError("agent_id cannot be empty")
        if not self.public_key: raise ValueError("public_key cannot be empty")
        if self.endpoint and not self.endpoint.startswith("https://"): raise ValueError("endpoint must use HTTPS")

"""SDK session model for conversation continuity."""
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class SdkSession:
    """A persisted SDK session for cross-message conversation continuity.

    Keyed by (swarm_id, peer_id) so each conversation partner in each
    swarm has an independent session.

    Attributes:
        swarm_id: The swarm this session belongs to.
        peer_id: The remote agent this conversation is with.
        session_id: The Claude SDK session identifier for ``resume=``.
        last_active: When the session was last used.
        state: Session state (active, expired).
    """

    swarm_id: str
    peer_id: str
    session_id: str
    last_active: datetime
    state: str = "active"

    def __post_init__(self) -> None:
        """Validate required fields."""
        if not self.swarm_id:
            raise ValueError("swarm_id cannot be empty")
        if not self.peer_id:
            raise ValueError("peer_id cannot be empty")
        if not self.session_id:
            raise ValueError("session_id cannot be empty")

    def is_expired(self, timeout_minutes: int) -> bool:
        """Check if this session has exceeded the timeout.

        Args:
            timeout_minutes: Maximum idle time in minutes.

        Returns:
            True if the session is older than the timeout.
        """
        elapsed = datetime.now(timezone.utc) - self.last_active
        return elapsed.total_seconds() > timeout_minutes * 60

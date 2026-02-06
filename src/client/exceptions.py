"""Exception types for the Agent Swarm Protocol client library."""


class SwarmError(Exception):
    """Base exception for all swarm client errors."""
    pass


class SignatureError(SwarmError):
    """Ed25519 signature creation or verification failed."""
    pass


class TransportError(SwarmError):
    """Network communication error."""
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TokenError(SwarmError):
    """Invite token is invalid, expired, or cannot be created."""
    pass


class NotMasterError(SwarmError):
    """Operation requires master role but agent is not master."""
    pass


class NotMemberError(SwarmError):
    """Operation requires swarm membership but agent is not a member."""
    pass


class RateLimitError(TransportError):
    """Request was rate limited by the server."""
    def __init__(self, message: str, retry_after: int | None = None, limit: int | None = None,
                 remaining: int | None = None, reset_at: int | None = None) -> None:
        super().__init__(message, status_code=429)
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at

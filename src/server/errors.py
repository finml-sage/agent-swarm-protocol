"""Custom exception types for the server."""
from typing import Optional, Any


class SwarmProtocolError(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class RateLimitedError(SwarmProtocolError):
    status_code = 429
    error_code = "RATE_LIMITED"

    def __init__(self, message: str = "Rate limit exceeded", reset_time: Optional[int] = None) -> None:
        details = {"retry_after": reset_time} if reset_time else None
        super().__init__(message, details)
        self.reset_time = reset_time

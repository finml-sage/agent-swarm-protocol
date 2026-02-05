"""Request logging middleware."""
import logging
import time
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("swarm.server")
SENSITIVE_FIELDS = frozenset({"signature", "public_key", "invite_token", "authorization", "x-api-key"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs incoming requests with sanitized details."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        start_time = time.perf_counter()
        agent_id = request.headers.get("X-Agent-ID", "unknown")
        protocol = request.headers.get("X-Swarm-Protocol", "unknown")
        logger.info("Request: %s %s agent=%s protocol=%s", request.method, request.url.path, agent_id, protocol)

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info("Response: %s %s status=%d duration=%.2fms", request.method, request.url.path, response.status_code, duration_ms)
        return response


def sanitize_dict(data: dict) -> dict:
    """Remove sensitive fields from a dictionary for logging."""
    result = {}
    for key, value in data.items():
        lower_key = key.lower()
        if lower_key in SENSITIVE_FIELDS:
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value)
        else:
            result[key] = value
    return result

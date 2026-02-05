"""Rate limiting middleware."""
import time
from collections import defaultdict
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware by client IP."""

    def __init__(self, app: ASGIApp, requests_per_minute: int = 60) -> None:
        super().__init__(app)
        self._requests_per_minute = requests_per_minute
        self._request_times: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        minute_ago = now - 60

        self._request_times[client_ip] = [t for t in self._request_times[client_ip] if t > minute_ago]
        current_count = len(self._request_times[client_ip])

        if current_count >= self._requests_per_minute:
            reset_time = int(min(self._request_times[client_ip]) + 60)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Rate limit exceeded",
                        "details": {"retry_after": reset_time},
                    }
                },
                headers={"Retry-After": str(reset_time)},
            )

        self._request_times[client_ip].append(now)
        response = await call_next(request)

        remaining = self._requests_per_minute - len(self._request_times[client_ip])
        response.headers["X-RateLimit-Limit"] = str(self._requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

"""HTTP transport layer with retry logic and connection pooling."""

import asyncio
import random
from typing import Any

import httpx

from .exceptions import RateLimitError, TransportError

PROTOCOL_VERSION = "0.1.0"


class Transport:
    def __init__(self, agent_id: str, timeout: float = 30.0, max_retries: int = 3) -> None:
        self._agent_id = agent_id
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "Transport":
        self._client = httpx.AsyncClient(http2=True, timeout=httpx.Timeout(self._timeout),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))
        return self

    async def __aexit__(self, exc_type: type | None, exc_val: Any, exc_tb: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "X-Agent-ID": self._agent_id, "X-Swarm-Protocol": PROTOCOL_VERSION}

    def _backoff(self, attempt: int) -> float:
        delay = min(1.0 * (2 ** attempt), 30.0)
        return max(0.1, delay + delay * 0.25 * (2 * random.random() - 1))

    def _retryable(self, code: int) -> bool:
        return code in (408, 429, 500, 502, 503, 504)

    async def post(self, url: str, data: dict, retry: bool = True) -> tuple[int, dict | None]:
        if not self._client:
            raise TransportError("Transport not initialized")
        return await self._request("POST", url, data, retry)

    async def get(self, url: str, retry: bool = True) -> tuple[int, dict | None]:
        if not self._client:
            raise TransportError("Transport not initialized")
        return await self._request("GET", url, None, retry)

    async def _request(self, method: str, url: str, data: dict | None, retry: bool) -> tuple[int, dict | None]:
        last_err: Exception | None = None
        attempts = self._max_retries if retry else 1
        for i in range(attempts):
            try:
                resp = await (self._client.post(url, json=data, headers=self._headers()) if method == "POST"
                              else self._client.get(url, headers=self._headers()))
                if resp.status_code == 429:
                    raise self._rate_limit_error(resp)
                if self._retryable(resp.status_code) and i < attempts - 1:
                    await asyncio.sleep(self._backoff(i))
                    continue
                try:
                    return resp.status_code, resp.json() if resp.content else None
                except Exception:
                    return resp.status_code, None
            except RateLimitError:
                raise
            except (httpx.TimeoutException, httpx.RequestError) as e:
                last_err = e
                if i < attempts - 1:
                    await asyncio.sleep(self._backoff(i))
        raise TransportError(f"Request failed after {attempts} attempts: {last_err}")

    def _rate_limit_error(self, resp: httpx.Response) -> RateLimitError:
        h = resp.headers
        return RateLimitError("Rate limited", int(h["Retry-After"]) if "Retry-After" in h else None,
            int(h["X-RateLimit-Limit"]) if "X-RateLimit-Limit" in h else None,
            int(h["X-RateLimit-Remaining"]) if "X-RateLimit-Remaining" in h else None,
            int(h["X-RateLimit-Reset"]) if "X-RateLimit-Reset" in h else None)

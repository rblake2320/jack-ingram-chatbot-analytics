"""Fault barriers for upstream calls: bounded retries with jitter, circuit breakers, typed errors."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

log = logging.getLogger(__name__)
T = TypeVar("T")


class UpstreamError(Exception):
    """An upstream dependency failed. ``kind`` is safe to show; details stay in logs."""

    def __init__(self, upstream: str, kind: str, detail: str = "", status: int | None = None) -> None:
        super().__init__(f"{upstream}: {kind} {detail}".strip())
        self.upstream = upstream
        self.kind = kind
        self.status = status


class _Retryable(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures; allows one probe after ``reset_after_s``."""

    def __init__(self, name: str, *, threshold: int = 5, reset_after_s: float = 30.0, clock=time.monotonic):
        self.name = name
        self.threshold = threshold
        self.reset_after_s = reset_after_s
        self.clock = clock
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self.opened_at >= self.reset_after_s else "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold or self.state == "half_open":
            if self.opened_at is None or self.state == "half_open":
                log.warning("circuit opened", extra={"upstream": self.name})
            self.opened_at = self.clock()


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.25,
    max_delay: float = 2.0,
    retry_on: tuple[type[BaseException], ...] = (_Retryable, httpx.TimeoutException, httpx.TransportError),
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> T:
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except retry_on as exc:
            last = exc
            if attempt == attempts - 1:
                break
            delay = min(max_delay, base_delay * (2**attempt)) * (0.5 + random.random())
            await sleep(delay)
    assert last is not None
    raise last


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    upstream: str,
    breaker: CircuitBreaker,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 8.0,
    attempts: int = 3,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> Any:
    """HTTP call with retries on 429/5xx/timeouts, breaker accounting, and JSON decoding."""
    if not breaker.allow():
        raise UpstreamError(upstream, "circuit_open")

    async def once() -> httpx.Response:
        response = await client.request(method, url, params=params, json=json_body, headers=headers, timeout=timeout)
        if response.status_code == 429 or response.status_code >= 500:
            raise _Retryable(response.status_code)
        return response

    try:
        response = await retry_async(once, attempts=attempts, sleep=sleep)
    except _Retryable as exc:
        breaker.record_failure()
        raise UpstreamError(upstream, "unavailable", status=exc.status) from exc
    except httpx.TimeoutException as exc:
        breaker.record_failure()
        raise UpstreamError(upstream, "timeout") from exc
    except httpx.TransportError as exc:
        breaker.record_failure()
        raise UpstreamError(upstream, "network_error", type(exc).__name__) from exc
    if response.status_code >= 400:
        # Our request was rejected (bad input / auth). Not an upstream health signal.
        raise UpstreamError(upstream, "rejected", status=response.status_code)
    try:
        data = response.json()
    except ValueError as exc:
        breaker.record_failure()
        raise UpstreamError(upstream, "bad_response", "invalid JSON") from exc
    breaker.record_success()
    return data

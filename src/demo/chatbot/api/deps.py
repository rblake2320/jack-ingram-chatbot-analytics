"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status

from ..app_state import Services
from ..security import check_admin, client_ip


def get_services(request: Request) -> Services:
    return request.app.state.services


def rate_limit(bucket: str, limit_attr: str, window_s: int) -> Callable[..., Awaitable[None]]:
    async def dependency(request: Request) -> None:
        services = get_services(request)
        ip = client_ip(request, services.settings)
        decision = await services.limiter.hit(f"{bucket}:{ip}", getattr(services.settings, limit_attr), window_s)
        if not decision.allowed:
            await services.analytics.record("rate_limited", None, bucket=bucket)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate_limited",
                headers={"Retry-After": str(decision.retry_after_s)},
            )

    return dependency


def limited(bucket: str, limit_attr: str, window_s: int = 60):
    return Depends(rate_limit(bucket, limit_attr, window_s))


def require_admin(request: Request) -> None:
    check_admin(request, get_services(request).secrets.admin_token)


def conversation_from_header(request: Request, *, required: bool = True) -> str | None:
    services = get_services(request)
    conv_id = services.tokens.verify(request.headers.get("x-conversation-token"))
    if conv_id is None and required:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_conversation_token")
    return conv_id

"""Liveness / readiness / version."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import __version__
from .deps import get_services

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    services = get_services(request)
    checks: dict[str, object] = {}
    try:
        checks["database"] = await services.db.run(services.db.ping)
    except Exception:  # readiness must report, not raise
        checks["database"] = False
    checks["llm"] = "unconfigured" if services.anthropic_client is None else services.agent.breaker.state
    checks["integrations"] = services.settings.integration_status()
    ok = checks["database"] is True
    return JSONResponse({"status": "ready" if ok else "degraded", "version": __version__, "checks": checks},
                        status_code=200 if ok else 503)  # fmt: skip


@router.get("/api/version")
async def version() -> dict:
    return {"version": __version__}

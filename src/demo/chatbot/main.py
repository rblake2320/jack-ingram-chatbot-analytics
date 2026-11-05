"""FastAPI application factory.

Run locally:   uvicorn chatbot.main:app --reload
Production:    uvicorn chatbot.main:app --host 0.0.0.0 --port $PORT --workers 2
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import admin, chat, health, pages, public
from .app_state import build_services, shutdown, start_background
from .config import PACKAGE_DIR, Settings, get_settings
from .ledger import IdempotencyConflict
from .logging_setup import configure_logging
from .middleware import (
    BodyLimitMiddleware,
    CSRFGuardMiddleware,
    Message,
    Receive,
    RequestContextMiddleware,
    Scope,
    SecurityHeadersMiddleware,
    Send,
)
from .services.common import ServiceError

log = logging.getLogger("chatbot")


class ErrorBarrierMiddleware:
    """Innermost barrier: any unhandled exception becomes a generic JSON 500 (no stack traces leak)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("unhandled error")
            if started:
                raise
            request_id = scope.get("state", {}).get("request_id", "-")
            response = JSONResponse({"error": "internal_error", "request_id": request_id}, status_code=500)
            await response(scope, receive, send)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def create_app(
    settings: Settings | None = None,
    *,
    http_transport: httpx.AsyncBaseTransport | None = None,
    anthropic_client: Any = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = build_services(settings, http_transport=http_transport, anthropic_client=anthropic_client)
        app.state.services = services
        start_background(services)
        log.info("started", extra={"event": "startup"})
        try:
            yield
        finally:
            await shutdown(services)

    docs = not settings.is_production
    app = FastAPI(
        title="Jack Ingram Motors AI Assistant",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "message": exc.message, "request_id": _request_id(request)},
                            status_code=exc.status)  # fmt: skip

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_conflict(request: Request, exc: IdempotencyConflict) -> JSONResponse:
        return JSONResponse(
            {
                "error": "idempotency_conflict",
                "message": "This Idempotency-Key was already used for a different request.",
            },
            status_code=409,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(p) for p in err.get("loc", ())], "msg": str(err.get("msg", ""))[:200], "type": err.get("type")}
            for err in exc.errors()[:20]
        ]  # never echo the submitted values back
        return JSONResponse({"error": "validation_error", "details": details, "request_id": _request_id(request)},
                            status_code=422)  # fmt: skip

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "error"
        return JSONResponse({"error": detail, "request_id": _request_id(request)}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))  # fmt: skip

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(public.router)
    app.include_router(admin.router)
    app.include_router(pages.router)
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    # Middleware: the LAST one added is the OUTERMOST.
    app.add_middleware(ErrorBarrierMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["content-type", "x-conversation-token", "idempotency-key"],
            max_age=600,
        )
    app.add_middleware(CSRFGuardMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, frame_ancestors=settings.frame_ancestors, hsts=settings.is_production)
    app.add_middleware(RequestContextMiddleware)
    return app


def _lazy_app() -> FastAPI:
    return create_app()


app = _lazy_app()

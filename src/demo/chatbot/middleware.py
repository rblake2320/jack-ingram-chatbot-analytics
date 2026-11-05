"""Pure-ASGI middleware: request ids + access log, security headers, body-size cap, CSRF guard."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import urlsplit

from .logging_setup import request_id_var

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

log = logging.getLogger("chatbot.access")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


async def _send_json(send: Send, status: int, body: dict[str, Any], headers: list[tuple[bytes, bytes]]) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode("ascii")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path not in ("/health",):
                log.info(
                    "request",
                    extra={
                        "event": "http_request",
                        "method": scope.get("method"),
                        "path": path,
                        "status": status_holder["status"],
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
            request_id_var.reset(token)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, frame_ancestors: list[str], hsts: bool) -> None:
        self.app = app
        ancestors = " ".join(frame_ancestors) if frame_ancestors else "'none'"
        csp = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
            f"form-action 'self'; frame-ancestors {ancestors}"
        )
        self.headers: list[tuple[bytes, bytes]] = [
            (b"content-security-policy", csp.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
            (b"cross-origin-opener-policy", b"same-origin"),
        ]
        if not frame_ancestors:
            self.headers.append((b"x-frame-options", b"DENY"))
        if hsts:
            self.headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope.get("path", "").startswith("/api/")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(self.headers)
                if is_api:
                    headers.append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodyLimitMiddleware:
    """Reject oversized bodies (declared or chunked) before the app parses them."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await _send_json(send, 413, {"error": "payload_too_large"}, [])
                    return
            except ValueError:
                await _send_json(send, 400, {"error": "invalid_content_length"}, [])
                return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > self.max_bytes:
                await _send_json(send, 413, {"error": "payload_too_large"}, [])
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break
        buffered = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class CSRFGuardMiddleware:
    """State-changing /api/ calls must be JSON and, if an Origin is sent, same-origin or allow-listed.

    Browsers cannot send ``application/json`` cross-origin without a CORS preflight, which we
    only grant to configured origins, so this closes form-post and text/plain CSRF vectors.
    """

    _UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app: ASGIApp, *, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in self._UNSAFE
            or not scope.get("path", "").startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        content_type = headers.get(b"content-type", b"").decode("latin-1").split(";")[0].strip().lower()
        if content_type != "application/json":
            await _send_json(send, 415, {"error": "unsupported_media_type", "expected": "application/json"}, [])
            return
        origin = headers.get(b"origin", b"").decode("latin-1").strip()
        if origin and origin != "null":
            host = headers.get(b"host", b"").decode("latin-1").lower()
            origin_host = urlsplit(origin).netloc.lower()
            if origin_host != host and origin.rstrip("/").lower() not in self.allowed:
                await _send_json(send, 403, {"error": "cross_origin_forbidden"}, [])
                return
        elif origin == "null":
            await _send_json(send, 403, {"error": "cross_origin_forbidden"}, [])
            return
        await self.app(scope, receive, send)

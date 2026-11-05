"""Shared fixtures. Every test gets its own data directory, secrets and SQLite database."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
from anthropic.types.beta import BetaMessage
from fastapi.testclient import TestClient

from chatbot.config import Settings
from chatbot.main import create_app

ADMIN_TOKEN = "admin-" + "t" * 40


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "test",
        "data_dir": tmp_path / "data",
        "background_workers": False,
        "session_secret": "s" * 48,
        "ledger_hmac_key": "l" * 48,
        "webhook_signing_secret": "w" * 48,
        "admin_token": ADMIN_TOKEN,
        "appointment_min_lead_minutes": 0,
        "log_level": "WARNING",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture
def services(tmp_path: Path, router: Router):
    """Service container without the HTTP app (for service-level tests)."""
    from chatbot.app_state import build_services, shutdown

    built = build_services(make_settings(tmp_path), http_transport=router.transport())
    yield built
    asyncio.run(shutdown(built))


# --- fake Anthropic client (real SDK response types) --------------------------------------
def message(
    content: list[dict[str, Any]], stop: str = "end_turn", *, usage: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 100, "output_tokens": 20},
    }


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def thinking_block(sig: str = "sig-1") -> dict[str, Any]:
    return {"type": "thinking", "thinking": "", "signature": sig}


def tool_use(name: str, tool_input: dict[str, Any], tool_id: str = "toolu_1") -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def api_error(cls: type[anthropic.APIStatusError], status: int, msg: str = "error") -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(msg, response=httpx2.Response(status, request=request), body=None)


class FakeMessages:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(copy.deepcopy(kwargs))
        if not self.script:
            raise AssertionError("fake Anthropic script exhausted")
        item = self.script.pop(0)
        if callable(item):
            item = item(kwargs)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, (int, float)):  # sleep seconds, then end_turn (deadline tests)
            await asyncio.sleep(item)
            item = message([text_block("late")])
        return BetaMessage.model_validate(item)


class FakeAnthropic:
    def __init__(self, script: list[Any]) -> None:
        self.messages = FakeMessages(script)
        self.beta = SimpleNamespace(messages=self.messages)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.messages.calls


# --- HTTP mock transport --------------------------------------------------------------------
class Router:
    """Route (method, host+path prefix) -> handler(request) for httpx.MockTransport."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, str, Callable[[httpx.Request], httpx.Response]]] = []
        self.requests: list[httpx.Request] = []

    def add(self, method: str, prefix: str, handler: Callable[[httpx.Request], httpx.Response] | dict | list) -> None:
        if not callable(handler):
            payload = handler
            handler = lambda request, payload=payload: httpx.Response(200, json=payload)  # noqa: E731
        self.routes.append((method, prefix, handler))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        target = request.url.host + request.url.path
        for method, prefix, handler in self.routes:
            if request.method == method and target.startswith(prefix):
                return handler(request)
        return httpx.Response(404, json={"error": "no route", "target": target})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def router() -> Router:
    return Router()


# --- app clients ------------------------------------------------------------------------------
@pytest.fixture
def app_factory(tmp_path: Path, router: Router) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def factory(*, anthropic_client: Any = None, **overrides: Any) -> TestClient:
        app = create_app(make_settings(tmp_path, **overrides), http_transport=router.transport(),
                         anthropic_client=anthropic_client)  # fmt: skip
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(app_factory: Callable[..., TestClient]) -> TestClient:
    return app_factory()


def services_of(client: TestClient):
    return client.app.state.services


def chat(client: TestClient, text: str, token: str | None = None) -> dict[str, Any]:
    headers = {"X-Conversation-Token": token} if token else {}
    response = client.post("/api/chat", json={"message": text}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def first_slot(client: TestClient, department: str = "service") -> str:
    data = client.get("/api/appointments/availability", params={"department": department, "days": 7}).json()
    assert data["slots"], data
    return data["slots"][0]["start"]


def dump(value: Any) -> str:
    return json.dumps(value, default=str)

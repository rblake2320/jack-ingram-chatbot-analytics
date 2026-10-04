"""Registered acceptance controls; synthetic input, no paid API calls."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from src.demo.api_router import APIRouter
from src.demo.app import create_app
from src.demo.claude_client import ClaudeClient, ProviderError
from src.demo.inventory_db import InventoryDB
from src.demo.routing import INTENTS, LayaRouter, baseline
from src.demo.store import ConversationChanged, Store

SECRET = "test-session-secret-at-least-32-characters"
TOKEN = "test-admin-token-at-least-32-characters"


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": SECRET,
            "ADMIN_TOKEN": TOKEN,
            "DATABASE": str(tmp_path / "chat.db"),
            "CHAT_PROVIDER": "local",
            "ENABLE_LAYA": False,
            "ENABLE_ANALYTICS": True,
            "RATE_LIMIT": 200,
        }
    )


def test_entry_and_assets(app):
    client = app.test_client()
    for path in ("/", "/analytics", "/static/app.css", "/static/chat.js", "/static/analytics.js"):
        assert client.get(path).status_code == 200
    health = client.get("/health").json
    assert health["status"] == "healthy" and health["inventory"] == "demo"
    assert "unsafe-inline" not in client.get("/").headers["Content-Security-Policy"]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "hello",
        {},
        {"message": 7},
        {"message": " "},
        {"message": "a" * 2001},
        {"message": "hi", "analytics_consent": "yes"},
    ],
)
def test_bad_input(app, payload):
    result = app.test_client().post("/api/chat", data=json.dumps(payload), content_type="application/json")
    assert result.status_code == 400 and "error" in result.json


def test_transport_barriers(app):
    c = app.test_client()
    assert c.post("/api/chat", data="x").status_code == 415
    assert c.post("/api/chat", data="{", content_type="application/json").status_code == 400
    assert c.post("/api/chat", json={"message": "x" * 20000}).status_code == 413
    assert (
        c.post(
            "/api/chat", json={"message": "hello"}, headers={"Origin": "https://untrusted.invalid"}
        ).status_code
        == 403
    )
    assert c.post("/api/reset", json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert (
        c.post("/api/chat", json={"message": "hello"}, headers={"Origin": "http://localhost"}).status_code
        == 200
    )


def test_malformed_origin_denied(app):
    assert (
        app.test_client()
        .post("/api/chat", json={"message": "hi"}, headers={"Origin": "http://["})
        .status_code
        == 403
    )


def test_untrusted_host_denied(app):
    assert app.test_client().get("/health", headers={"Host": "untrusted.invalid"}).status_code == 400


def test_non_ascii_admin_header_denied(app):
    assert (
        app.test_client().get("/api/analytics", headers={"Authorization": "Bearer snowman-☃"}).status_code
        == 401
    )


def test_privacy_wins_failed_provider(app):
    started, release = Event(), Event()

    class Router:
        def process_request(self, message, history):
            started.set()
            assert release.wait(5)
            raise ProviderError("provider_timeout", 504)

    concurrent = create_app(dict(app.config), Router())
    c, reset = concurrent.test_client(), concurrent.test_client()
    c.get("/")
    reset.set_cookie("session", c.get_cookie("session").value)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(c.post, "/api/chat", json={"message": "slow", "analytics_consent": True})
        assert started.wait(5)
        assert reset.post("/api/privacy", json={}).status_code == 200
        release.set()
        assert pending.result().status_code == 504
    assert concurrent.extensions["store"].summary()["messages"] == 0


def test_local_routes(app):
    c = app.test_client()
    cases = [
        ("hours", "Monday-Friday", "hours"),
        ("Audi inventory", "Q5", "inventory"),
        ("Volvo inventory", "No matching sample", "inventory"),
        ("Where are you located?", "Eastern Blvd", "contact"),
        ("service", "Factory authorized", "service"),
        ("Book a test drive", "no appointment has been reserved", "appointment"),
        ("Hello", "Welcome", "other"),
    ]
    for message, needle, intent in cases:
        result = c.post("/api/chat", json={"message": message})
        assert result.status_code == 200 and needle in result.json["response"]
        assert result.json["intent"] == intent and result.json["data_status"] == "demo_not_live"


def test_receiving_session_isolation_and_reset(app):
    class Router:
        seen = []

        def process_request(self, message, history):
            self.seen.append((message, history))
            return {"response": "reply", "source": "local", "intent": "other", "brand": "all"}

    router = Router()
    isolated = create_app(dict(app.config), router)
    a, b = isolated.test_client(), isolated.test_client()
    aid = a.post("/api/chat", json={"message": "alice"}).json["conversation_id"]
    bid = b.post("/api/chat", json={"message": "bob"}).json["conversation_id"]
    assert aid != bid and router.seen[1][1] == []
    a.post("/api/chat", json={"message": "follow up"})
    assert router.seen[2][1][0]["content"] == "alice"
    assert a.post("/api/reset", json={}).json["conversation_id"] != aid
    a.post("/api/chat", json={"message": "reset"})
    assert router.seen[3][1] == []
    b.post("/api/chat", json={"message": "again"})
    assert router.seen[4][1][0]["content"] == "bob"


def test_consent_summary_and_forget(app):
    c = app.test_client()
    auth = {"Authorization": "Bearer " + TOKEN}
    c.post("/api/chat", json={"message": "hours"})
    assert c.get("/api/analytics", headers=auth).json["messages"] == 0
    c.post("/api/chat", json={"message": "audi inventory", "analytics_consent": True})
    data = c.get("/api/analytics", headers=auth).json
    assert data["messages"] == data["visitors"] == data["successes"] == 1
    assert data["window"] == "all" and data["coverage_start"]
    with app.extensions["store"].connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
    assert not columns & {"message", "user_message", "user_agent", "ip", "assistant_response"}
    c.post("/api/privacy", json={})
    assert c.get("/api/analytics", headers=auth).json["messages"] == 0


def test_admin_windows_and_rate_limit(app):
    c = app.test_client()
    assert c.get("/api/analytics").status_code == 401
    assert c.get("/api/analytics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    auth = {"Authorization": "Bearer " + TOKEN}
    for window in ("all", "30", "7"):
        assert c.get("/api/analytics?window=" + window, headers=auth).status_code == 200
    assert c.get("/api/analytics?window=invalid", headers=auth).status_code == 400
    app.config["RATE_LIMIT"] = 2
    for _ in range(2):
        assert app.test_client().post("/api/chat", json={"message": "hi"}).status_code == 200
    assert app.test_client().post("/api/chat", json={"message": "hi"}).status_code == 429


def test_reset_wins_inflight(app):
    started, release = Event(), Event()

    class Router:
        def process_request(self, message, history):
            started.set()
            assert release.wait(5)
            return {"response": "stale", "source": "local", "intent": "other", "brand": "all"}

    concurrent = create_app(dict(app.config), Router())
    c, reset = concurrent.test_client(), concurrent.test_client()
    c.get("/")
    reset.set_cookie("session", c.get_cookie("session").value)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(c.post, "/api/chat", json={"message": "slow", "analytics_consent": True})
        assert started.wait(5)
        assert reset.post("/api/privacy", json={}).status_code == 200
        release.set()
        assert pending.result().status_code == 409
    assert concurrent.extensions["store"].summary()["messages"] == 0


def test_store_restart_bounds_and_stale_revision(app):
    store = app.extensions["store"]
    version, _ = store.history("same")
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(24)]
    store.finish("same", version, history)
    with pytest.raises(ConversationChanged):
        store.finish("same", version, history)
    assert len(Store(store.path).history("same")[1]) == 20
    with store.connect() as db:
        db.execute("UPDATE conversations SET updated=0")
    assert store.history("same") == (0, [])


def test_expired_offers_and_model_filter():
    db = InventoryDB()
    assert db.get_offers() == db.get_offers("nissan") == []
    assert len(db.get_inventory(model="Q5")) == 1


def test_suv_request_filters_body_style(app):
    response = app.test_client().post("/api/chat", json={"message": "Do you have any SUVs?"})
    assert "Rogue" in response.json["response"] and "Altima" not in response.json["response"]


def test_model_request_without_brand(app):
    response = app.test_client().post("/api/chat", json={"message": "Q5 inventory"})
    assert "Audi Q5" in response.json["response"] and "Altima" not in response.json["response"]


def valid():
    return {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "answer"}],
        "usage": {"input_tokens": 3, "output_tokens": 2},
    }


def provider(body=None, status=200, handler=None):
    def default(request):
        return httpx.Response(status, json=body)

    return ClaudeClient("synthetic-key", "test-model", httpx.MockTransport(handler or default))


def test_provider_context():
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json=valid())

    assert (
        provider(handler=handler).send_message("hi", [{"role": "user", "content": "prior"}], {})["response"]
        == "answer"
    )
    assert received[0]["messages"][-1]["content"] == "hi"
    assert received[0]["messages"][0]["content"] == "prior"


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"stop_reason": "max_tokens"},
        {"stop_reason": "end_turn", "content": []},
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": ""}]},
        {"stop_reason": "end_turn", "content": [{"type": "tool_use"}]},
        {"stop_reason": "end_turn", "content": ["invalid"]},
        {"stop_reason": "end_turn", "content": [{"type": "text", "text": 12}]},
        dict(valid(), usage={"input_tokens": True}),
        dict(valid(), usage={"input_tokens": -1}),
        dict(valid(), usage=[]),
    ],
)
def test_bad_provider_body(body):
    with pytest.raises(ProviderError):
        provider(body).send_message("hi", [], {})


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_redaction(status):
    with pytest.raises(ProviderError) as error:
        provider({"error": "private-details"}, status).send_message("hi", [], {})
    assert "private-details" not in str(error.value)


def test_provider_timeouts_and_size():
    def timeout(request):
        raise httpx.ReadTimeout("private-details")

    with pytest.raises(ProviderError, match="provider_timeout"):
        provider(handler=timeout).send_message("hi", [], {})

    def oversized(request):
        return httpx.Response(200, content=b"x" * 70000)

    with pytest.raises(ProviderError, match="too_large"):
        provider(handler=oversized).send_message("hi", [], {})
    with pytest.raises(ProviderError, match="not_configured"):
        ClaudeClient("", "test").send_message("hi", [], {})


def test_failed_provider_does_not_append(app):
    class Failing:
        def send_message(self, *args):
            raise ProviderError("provider_timeout", 504)

    failed = create_app(dict(app.config), APIRouter(Failing()))
    c = failed.test_client()
    r = c.post("/api/chat", json={"message": "a complex request", "analytics_consent": True})
    assert r.status_code == 504 and r.json["error"] == "provider_timeout"
    with c.session_transaction() as state:
        conversation = state["conversation_id"]
    assert failed.extensions["store"].history(conversation)[1] == []
    assert failed.extensions["store"].summary()["errors"] == 1


def test_storage_failure_classified(app):
    with app.extensions["store"].connect() as db:
        db.execute("DROP TABLE conversations")
    r = app.test_client().post("/api/chat", json={"message": "hi"})
    assert r.status_code == 503 and r.json["error"] == "storage_unavailable"


def test_laya_unavailable_and_malformed():
    router = LayaRouter()
    assert router.classify("hello")["status"] == "unavailable"

    class Agent:
        class tok:
            @staticmethod
            def encode(text):
                return list(range(10))

        def predict(self, *args):
            return {"answers": {"intent": {"choice": "hours", "probs": {k: float("nan") for k in INTENTS}}}}

    router.agent = Agent()
    assert router.classify("hello")["status"] == "invalid_output"
    assert router.classify("a" * 501)["status"] == "input_too_long"


@pytest.mark.parametrize(
    "message,intent",
    [
        ("opening hours", "hours"),
        ("inventory", "inventory"),
        ("service", "service"),
        ("booking", "appointment"),
        ("hello", "other"),
        ("showcase", "other"),
        ("Do you have any SUVs?", "inventory"),
    ],
)
def test_word_boundaries(message, intent):
    assert baseline(message) == intent

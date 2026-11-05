"""HTTP hardening: headers, CSRF, body caps, rate limits, admin auth, error hygiene, token tampering."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from chatbot.main import create_app

from .conftest import ADMIN_TOKEN, chat, make_settings


def test_security_headers_on_pages_and_api(client):
    page = client.get("/")
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["x-frame-options"] == "DENY"
    api = client.get("/api/dealership")
    assert api.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in api.headers  # HSTS only in production


def test_frame_ancestors_configurable_for_embedding(app_factory):
    client = app_factory(frame_ancestors=["https://www.jackingram.com"])
    response = client.get("/")
    assert "frame-ancestors https://www.jackingram.com" in response.headers["content-security-policy"]
    assert "x-frame-options" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [{"content-type": "text/plain"}, {"content-type": "application/x-www-form-urlencoded"},
     {"content-type": "multipart/form-data; boundary=x"}, {}],
)  # fmt: skip
def test_non_json_posts_rejected(client, headers):
    response = client.post("/api/chat", content=b'{"message": "hi"}', headers=headers)
    assert response.status_code == 415


def test_cross_origin_post_rejected_same_origin_allowed(client):
    evil = client.post("/api/chat", json={"message": "hi"}, headers={"origin": "https://evil.example"})
    assert evil.status_code == 403
    null_origin = client.post("/api/chat", json={"message": "hi"}, headers={"origin": "null"})
    assert null_origin.status_code == 403
    same = client.post("/api/chat", json={"message": "hi"}, headers={"origin": "http://testserver"})
    assert same.status_code == 200


def test_cors_allow_list(app_factory):
    client = app_factory(cors_origins=["https://www.jackingram.com"])
    ok = client.post("/api/chat", json={"message": "hi"}, headers={"origin": "https://www.jackingram.com"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "https://www.jackingram.com"
    preflight = client.options("/api/chat", headers={"origin": "https://www.jackingram.com",
                                                     "access-control-request-method": "POST"})  # fmt: skip
    assert preflight.status_code == 200


def test_declared_oversized_body_rejected(client):
    response = client.post("/api/chat", content=b"{" + b" " * (70 * 1024) + b"}",
                           headers={"content-type": "application/json"})  # fmt: skip
    assert response.status_code == 413


def test_chunked_oversized_body_rejected(client):
    def body():
        for _ in range(80):
            yield b" " * 1024

    response = client.post("/api/chat", content=body(), headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_invalid_content_length_rejected(client):
    response = client.post(
        "/api/chat", content=b"{}", headers={"content-type": "application/json", "content-length": "abc"}
    )
    assert response.status_code in (400, 413)


def test_message_length_limit_and_no_input_echo(client):
    secret = "TOPSECRET-" + "x" * 2100
    response = client.post("/api/chat", json={"message": secret})
    assert response.status_code == 422 and "TOPSECRET" not in response.text
    schema_violation = client.post(
        "/api/finance/payment", json={"price": "TOPSECRET", "apr_percent": 5, "term_months": 60}
    )
    assert schema_violation.status_code == 422 and "TOPSECRET" not in schema_violation.text


def test_empty_message_rejected(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    blank = client.post("/api/chat", json={"message": "   \x00​  "})
    assert blank.status_code == 422 and blank.json()["error"] == "empty_message"


def test_rate_limit_returns_429_with_retry_after(app_factory):
    client = app_factory(rate_limit_chat_per_minute=3)
    codes = [client.post("/api/chat", json={"message": "hours?"}).status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    blocked = client.post("/api/chat", json={"message": "hours?"})
    assert int(blocked.headers["retry-after"]) >= 1


def test_spoofed_forwarded_for_does_not_bypass_limit(app_factory):
    client = app_factory(rate_limit_chat_per_minute=2)
    codes = [client.post("/api/chat", json={"message": "hi"}, headers={"x-forwarded-for": f"10.0.0.{i}"}).status_code
             for i in range(3)]  # fmt: skip
    assert codes[-1] == 429


def test_configured_proxy_header_separates_clients(app_factory):
    client = app_factory(rate_limit_chat_per_minute=1, client_ip_header="do-connecting-ip")
    a = client.post("/api/chat", json={"message": "hi"}, headers={"do-connecting-ip": "203.0.113.1"})
    b = client.post("/api/chat", json={"message": "hi"}, headers={"do-connecting-ip": "203.0.113.2"})
    a2 = client.post("/api/chat", json={"message": "hi"}, headers={"do-connecting-ip": "203.0.113.1"})
    assert (a.status_code, b.status_code, a2.status_code) == (200, 200, 429)


@pytest.mark.parametrize(
    "header", [None, "Bearer wrong", "Basic " + ADMIN_TOKEN, "Bearer " + ADMIN_TOKEN + "x", "Bearer "]
)
def test_admin_requires_exact_bearer(client, header):
    headers = {"Authorization": header} if header else {}
    assert client.get("/api/admin/analytics/summary", headers=headers).status_code == 401


def test_admin_works_with_token_and_is_disabled_without_one(client, app_factory, admin_headers):
    assert client.get("/api/admin/analytics/summary", headers=admin_headers).status_code == 200
    disabled = app_factory(admin_token=None)
    assert disabled.get("/api/admin/analytics/summary", headers=admin_headers).status_code == 503


def test_unhandled_error_is_generic_json_with_request_id(client, monkeypatch):
    services = client.app.state.services

    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail /etc/passwd")

    monkeypatch.setattr(services.inventory, "search", boom)
    response = client.get("/api/inventory/search", headers={"x-request-id": "req-abcdef123"})
    assert response.status_code == 500
    assert response.json() == {"error": "internal_error", "request_id": "req-abcdef123"}
    assert "passwd" not in response.text and response.headers["x-content-type-options"] == "nosniff"


def test_request_id_sanitised(client):
    good = client.get("/health", headers={"x-request-id": "abcDEF123_-xyz"})
    assert good.headers["x-request-id"] == "abcDEF123_-xyz"
    bad = client.get("/health", headers={"x-request-id": "bad id\r\ninjected"})
    assert bad.headers["x-request-id"] != "bad id\r\ninjected" and len(bad.headers["x-request-id"]) == 32


def test_tampered_conversation_token_cannot_read_or_continue(client):
    first = chat(client, "hello")
    token = first["conversation_token"]
    forged = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert client.get("/api/chat/messages", headers={"X-Conversation-Token": forged}).status_code == 401
    assert client.get("/api/chat/messages", headers={"X-Conversation-Token": "v1.c_x.y"}).status_code == 401
    resumed = chat(client, "hello again", token=forged)
    assert resumed["new_conversation"] is True and resumed["conversation_token"] != token


def test_production_mode_hardening(tmp_path):
    strong = "p" * 40
    settings = make_settings(tmp_path, environment="production", session_secret=strong, ledger_hmac_key=strong,
                             admin_token=strong)  # fmt: skip
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404
        assert "max-age=31536000" in client.get("/health").headers["strict-transport-security"]
        assert not (tmp_path / "data" / ".dev-secrets.json").exists()
        with client.app.state.services.db.read() as conn:  # no demo service records seeded in production
            assert conn.execute("SELECT COUNT(*) FROM service_records").fetchone()[0] == 0


def test_ready_reports_integrations_without_secrets(client):
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json()["checks"]["database"] is True
    assert ADMIN_TOKEN not in ready.text and "s" * 48 not in ready.text

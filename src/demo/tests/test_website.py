"""Acceptance for real location facts and an embedded, cookie-independent conversation."""

import re

import pytest

from src.demo.api_router import APIRouter
from src.demo.app import create_app
from src.demo.knowledge_base import LOCATIONS


@pytest.fixture
def site(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "website-test-session-secret-32-characters",
            "ADMIN_TOKEN": "website-test-admin-secret-32-characters",
            "DATABASE": str(tmp_path / "website.db"),
            "CHAT_PROVIDER": "local",
            "ENABLE_LAYA": False,
            "WIDGET_ORIGINS": ["https://www.jackingram.com"],
            "RATE_LIMIT": 200,
        }
    )


def test_all_stores_have_sourced_facts():
    assert set(LOCATIONS) == {
        "audi",
        "mercedes",
        "nissan",
        "porsche",
        "volkswagen",
        "volvo",
        "signature",
        "body-shop",
    }
    for row in LOCATIONS.values():
        assert row["address"] and row["phone"] and row["sources"][0]["retrieved_at"]
        assert row["website"].startswith("https://")


def test_service_hours_differ_from_sales():
    router = APIRouter()
    assert "07:00–17:30" in router.process_request("Nissan service hours", [])["response"]
    assert "08:30–19:00" in router.process_request("Nissan sales hours", [])["response"]


@pytest.mark.parametrize(
    "store,address",
    [
        ("Porsche", "245 Eastern"),
        ("Audi", "241 Eastern"),
        ("body shop", "5648 Eddins"),
        ("Signature", "235 N Eastern"),
    ],
)
def test_store_contact(store, address):
    result = APIRouter().process_request(store + " address", [])
    assert address in result["response"]
    assert result["citations"] and result["source"] == "official_website"
    assert "1000 Eastern" not in result["response"]


def test_followup_keeps_store_and_website_inventory():
    result = APIRouter().process_request(
        "What are the service hours?", [{"role": "user", "content": "Porsche address"}]
    )
    assert "Porsche" in result["response"] and "Closed" in result["response"]
    stock = APIRouter().process_request("Audi inventory", [])
    assert stock["source"] == "official_website" and "sample price" not in stock["response"]
    assert any(link["kind"] == "inventory" and "audimontgomery.com" in link["url"] for link in stock["links"])


def test_all_locations_and_ambiguous_hours():
    result = APIRouter().process_request("All locations", [])
    assert all(row["address"] in result["response"] for row in LOCATIONS.values())
    assert "Which location" in APIRouter().process_request("Service hours", [])["response"]


def test_unpublished_hours_and_conflict_are_visible():
    result = APIRouter().process_request("Audi hours", [])
    assert "structured data" in result["response"] and "confirm" in result["response"].lower()
    result = APIRouter().process_request("Volvo service hours", [])
    assert "Saturday: Not published" in result["response"]


def widget_token(client):
    page = client.get("/widget?parent=https://www.jackingram.com")
    assert page.status_code == 200
    return re.search(r'data-session-token="([^"]+)"', page.text).group(1)


def test_embed_ancestors_scoped_and_validated(site):
    client = site.test_client()
    page = client.get("/widget?parent=https://www.jackingram.com")
    assert "frame-ancestors https://www.jackingram.com;" in page.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in client.get("/analytics").headers["Content-Security-Policy"]
    for parent in (
        "https://evil.invalid",
        "https://www.jackingram.com.evil.invalid",
        "http://[",
        "https://www.jackingram.com/path",
    ):
        assert client.get("/widget", query_string={"parent": parent}).status_code == 403


def test_embed_no_cookies_history_reset_and_privacy(site):
    client = site.test_client(use_cookies=False)
    token = widget_token(client)
    headers = {"X-Chat-Session": token}
    first = client.post(
        "/api/chat", headers=headers, json={"message": "Porsche address", "analytics_consent": True}
    )
    assert first.status_code == 200
    second = client.post("/api/chat", headers=headers, json={"message": "Service hours"})
    assert "Porsche" in second.json["response"]
    reset = client.post("/api/privacy", headers=headers, json={})
    assert reset.status_code == 200 and reset.json["session_token"] != token
    # A deleted session must not be resurrected by a stolen/stale token.
    assert client.post("/api/chat", headers=headers, json={"message": "hello"}).status_code == 401
    headers["X-Chat-Session"] = reset.json["session_token"]
    assert (
        "Which location"
        in client.post("/api/chat", headers=headers, json={"message": "Hours"}).json["response"]
    )
    data = client.get(
        "/api/analytics", headers={"Authorization": "Bearer website-test-admin-secret-32-characters"}
    ).json
    assert data["messages"] == 0


def test_tampered_token_and_location_denied(site):
    client = site.test_client()
    assert (
        client.post("/api/chat", headers={"X-Chat-Session": "tampered"}, json={"message": "hi"}).status_code
        == 401
    )
    assert client.post("/api/chat", json={"message": "hi", "location_id": "evil"}).status_code == 400


def test_catalog_refresh_ignores_marketing_but_detects_hours():
    from scripts.collect_dealership_sources import business_facts

    original = {
        "name": "Synthetic Store",
        "description": "Old ad",
        "openingHoursSpecification": [{"opens": "08:00", "closes": "18:00"}],
    }
    changed_ad = {**original, "description": "New ad"}
    changed_hours = {**original, "openingHoursSpecification": [{"opens": "08:00", "closes": "19:00"}]}
    assert business_facts([original]) == business_facts([changed_ad])
    assert business_facts([original]) != business_facts([changed_hours])


def test_unreadable_source_is_unknown_not_a_fact_change():
    from scripts.collect_dealership_sources import compare_facts

    result = compare_facts([{"id": "porsche", "status": "blocked"}], {})
    assert result[0]["facts_changed"] is None


def test_stale_hours_require_refresh(monkeypatch):
    from src.demo.knowledge_base import CATALOG

    monkeypatch.setitem(CATALOG, "reviewed_at", "2000-01-01")
    result = APIRouter().process_request("Nissan service hours", [])
    assert "need a refresh" in result["response"] and "07:00" not in result["response"]
    assert result["facts_fresh"] is False


def test_deleted_widget_during_history_read_cannot_return(site, monkeypatch):
    client = site.test_client(use_cookies=False)
    token = widget_token(client)
    store = site.extensions["store"]
    original = store.history

    def reset_then_read(conversation, require_existing=False):
        store.reset(conversation)
        return original(conversation, require_existing=require_existing)

    monkeypatch.setattr(store, "history", reset_then_read)
    assert (
        client.post(
            "/api/chat", headers={"X-Chat-Session": token}, json={"message": "Porsche hours"}
        ).status_code
        == 401
    )

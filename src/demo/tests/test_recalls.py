import httpx
import pytest

from src.demo import recalls
from src.demo.api_router import APIRouter
from src.demo.app import create_app
from src.demo.vehicle_atlas import ATLAS, SYSTEMS_ATLAS

REAL_HTTP_CLIENT = httpx.Client


def test_recall_chat_contract_through_actual_flask_handler(tmp_path):
    client = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "recall-http-test-secret-32-characters",
            "DATABASE": str(tmp_path / "test.db"),
            "RATE_LIMIT": 200,
        }
    ).test_client()
    for text in (
        "I got a recall",
        "2025 Porsche 911 recalls",
        "2026 Atlas recalls",
        "2026 Porsche 911 recalls",
    ):
        reply = client.post("/api/chat", json={"message": text, "analytics_consent": False})
        assert reply.status_code == 200
        assert reply.json["response"] and reply.json["brand"]
    assert client.post("/api/chat", json={"message": "2025 Porsche 911 recalls"}).json["recall_cards"]


@pytest.fixture(autouse=True)
def offline_official_fixture(monkeypatch):
    recalls._cache.clear()

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def stream(self, *args, **kwargs):
            raise httpx.ConnectError("synthetic offline")

    monkeypatch.setattr(recalls.httpx, "Client", Client)


def test_official_snapshot_preserves_scope_remedy_and_safety_instruction():
    data = recalls.lookup("vw-atlas", 2026)
    assert data["status"] == "saved_snapshot" and data["vin_verified"] is False
    card = next(c for c in data["cards"] if c["campaign"] == "25V835000")
    assert card["do_not_drive"] is True and "not to drive" in card["remedy"]
    assert card["component_id"] is None and card["explorer_url"] is None


def test_porsche_camera_links_notice_to_explanatory_region_without_moving_model_year():
    data = recalls.lookup("porsche-911", 2025)
    card = next(c for c in data["cards"] if c["campaign"] == "25V896000")
    assert card["component_id"] == "rear-camera"
    assert "year=2025" in card["explorer_url"]
    assert "does not apply" in card["geometry_scope"]
    assert "free of charge" in card["remedy"]
    assert "rear-camera" in {c["id"] for c in SYSTEMS_ATLAS["components"]}


def test_failed_official_lookup_is_not_a_no_recall_or_vin_clearance():
    data = recalls.lookup("porsche-911", 2026)
    assert data["status"] == "unavailable" and "not a no-recall result" in data["error"]
    reply = APIRouter().process_request("2026 Porsche 911 recalls", [])
    assert "not a no-recall result" in reply["response"]
    assert reply["vin_verified"] is False


def test_recall_request_precedes_engine_context_and_shows_details_in_chat():
    reply = APIRouter().process_request(
        "2025 Porsche 911 recalls",
        [],
        vehicle_context={"vehicle_id": SYSTEMS_ATLAS["id"], "component_id": "engine"},
    )
    assert len(reply["recall_cards"]) == 2 and "explorer_action" not in reply
    assert reply["recall_status"] == "saved_snapshot"


def test_systems_context_is_scoped_and_unhashable_identity_rejected(tmp_path):
    client = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "systems-test-secret-32-characters-long",
            "DATABASE": str(tmp_path / "test.db"),
            "RATE_LIMIT": 200,
        }
    ).test_client()
    for context in ({"vehicle_id": []}, {"vehicle_id": ATLAS["id"], "component_id": "engine"}):
        assert (
            client.post("/api/chat", json={"message": "show engine", "vehicle_context": context}).status_code
            == 400
        )
    reply = client.post(
        "/api/chat", json={"message": "show engine", "vehicle_context": {"vehicle_id": SYSTEMS_ATLAS["id"]}}
    )
    assert reply.json["explorer_action"] == {"operation": "select", "component_id": "engine"}
    assert "473 hp" in reply.json["response"] and reply.json["citations"]
    assert client.get("/api/recalls?vehicle=http://evil.invalid&year=2026").status_code == 400
    assert client.get("/api/recalls?vehicle=porsche-911&year=2025").json["status"] == "saved_snapshot"


def test_recall_followup_and_campaign_number_keep_notice_in_product():
    router = APIRouter()
    assert router.process_request("I got a recall", [])["source"] == "nhtsa_recall_lookup"
    reply = router.process_request("2025 Porsche 911", [{"role": "user", "content": "I got a recall"}])
    assert len(reply["recall_cards"]) == 2
    assert router.process_request("show recall 25V896000", [])["recall_cards"]
    assert (
        router.process_request("Compare Rogue and Atlas", [{"role": "user", "content": "I got a recall"}])[
            "source"
        ]
        != "nhtsa_recall_lookup"
    )


@pytest.mark.parametrize("scenario", ["empty", "wrong_year", "malformed"])
def test_official_responses_are_validated_before_claiming_lookup_success(monkeypatch, scenario):
    row = dict(recalls.SNAPSHOTS["porsche-911:2025"]["recalls"][0])
    if scenario == "wrong_year":
        row["ModelYear"] = "2026"
    if scenario == "malformed":
        row["Remedy"] = {"text": "untrusted"}
    rows = [] if scenario == "empty" else [row]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"Count": len(rows), "results": rows})
    )
    monkeypatch.setattr(recalls.httpx, "Client", lambda **kwargs: REAL_HTTP_CLIENT(transport=transport))
    result = recalls.lookup("porsche-911", 2025)
    assert result["status"] == ("live" if scenario == "empty" else "saved_snapshot")
    assert result["vin_verified"] is False
    if scenario == "empty":
        assert result["cards"] == []

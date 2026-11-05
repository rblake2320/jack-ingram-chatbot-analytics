"""Leads (validation, atomicity, idempotency, ADF safety) and the CRM outbox (signing, retry, leases)."""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET

import httpx
import pytest
from pydantic import ValidationError

from chatbot.ledger import IdempotencyConflict
from chatbot.services.adf import build_adf
from chatbot.services.leads import LeadInput
from chatbot.services.outbox import Outbox, sign, verify_signature

from .conftest import ADMIN_TOKEN

LEAD = {"first_name": "Ann", "last_name": "Lee", "phone": "334-555-0142", "interest": "buy", "consent_to_contact": True}


def lead(**kw) -> LeadInput:
    return LeadInput(**(LEAD | kw))


@pytest.mark.parametrize(
    "bad",
    [
        {"consent_to_contact": False},
        {"phone": None, "email": None},
        {"phone": "555-0142"},
        {"phone": "(134) 555-0142"},
        {"email": "a@b"},
        {"email": "a..b@example.com"},
        {"first_name": "Robert'); DROP TABLE leads;--"},
        {"first_name": ""},
        {"interest": "steal"},
    ],
)
def test_lead_validation_rejects(bad):
    with pytest.raises(ValidationError):
        lead(**bad)


def test_lead_normalisation_strips_control_and_bidi():
    data = lead(phone="+1 (334) 555.0142", email="Ann@Example.COM", comments="hi\x00 there‮ evil\x1b[31m")
    assert data.phone == "+13345550142" and data.email == "Ann@example.com"
    assert "\x00" not in data.comments and "‮" not in data.comments and "\x1b" not in data.comments


def test_lead_write_is_atomic_row_ledger_outbox(tmp_path, router):
    from chatbot.app_state import build_services, shutdown

    from .conftest import make_settings

    svc = build_services(
        make_settings(tmp_path, crm_webhook_url="https://crm.example/hook"), http_transport=router.transport()
    )
    try:
        record, _ = svc.leads.create_sync(lead(), source="test")
        with svc.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1
            outbox = conn.execute("SELECT payload FROM outbox").fetchone()
            seq = conn.execute("SELECT ledger_seq FROM leads").fetchone()[0]
            entry = json.loads(conn.execute("SELECT payload FROM ledger WHERE seq = ?", (seq,)).fetchone()[0])
        assert entry["lead_id"] == record["id"] and "phone" not in json.dumps(entry)  # no PII in the ledger
        assert json.loads(outbox["payload"])["ledger"]["seq"] == seq

        def explode(*args, **kwargs):
            raise RuntimeError("crash between ledger append and outbox insert")

        with svc.db.read() as conn:
            ledger_before = conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
        svc.outbox.enqueue = explode
        with pytest.raises(RuntimeError):
            svc.leads.create_sync(lead(phone="334-555-0143"), source="test")
        with svc.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == ledger_before
            assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1
            assert svc.ledger.verify(conn).ok
    finally:
        asyncio.run(shutdown(svc))


def test_lead_idempotency(services):
    a, replay_a = services.leads.create_sync(lead(), source="test", idempotency_key="lead:k1")
    b, replay_b = services.leads.create_sync(lead(), source="test", idempotency_key="lead:k1")
    assert a["id"] == b["id"] and not replay_a and replay_b
    with pytest.raises(IdempotencyConflict):
        services.leads.create_sync(lead(comments="changed"), source="test", idempotency_key="lead:k1")


def test_adf_escapes_injection_and_parses():
    evil = "</comments><vendor><vendorname>Evil</vendorname></vendor><comments>& \"quotes\" 'x'"
    record = {"id": "lead_1", "created_at": "2026-11-05T10:00:00Z", "first_name": "Ann", "last_name": "O'Neil",
              "email": "ann@example.com", "phone": "+13345550142", "interest": "buy",
              "vehicle": {"year": 2026, "make": "Audi", "model": "Q5", "vin": "1HGCM82633A004352"},
              "comments": evil + "\x00\x0b"}  # fmt: skip
    xml = build_adf(record, vendor_name="Jack Ingram Motors")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<?adf version="1.0"?>')
    root = ET.fromstring(xml.split("\n", 2)[2])
    assert root.find("prospect/customer/comments").text == evil
    assert [v.text for v in root.iter("vendorname")] == ["Jack Ingram Motors"]
    assert root.find("prospect/vehicle/vin").text == "1HGCM82633A004352"
    assert root.find("prospect/customer/contact/name[@part='last']").text == "O'Neil"


def test_lead_api_masks_and_replays(client):
    headers = {"Idempotency-Key": "lead-key-0001"}
    first = client.post("/api/leads", json=LEAD | {"email": "ann@example.com"}, headers=headers)
    assert first.status_code == 201
    body = first.json()
    assert body["phone"] == "***-***-0142" and body["email"] == "a***@example.com"
    assert (
        client.post("/api/leads", json=LEAD | {"email": "ann@example.com"}, headers=headers).json()["replayed"] is True
    )


def test_records_verify_detects_tampered_business_row(client, admin_headers):
    client.post("/api/leads", json=LEAD)
    assert client.get("/api/admin/records/verify", headers=admin_headers).json()["ok"] is True
    services = client.app.state.services
    with services.db.tx() as conn:
        conn.execute("UPDATE leads SET phone = '+12055550000'")  # redirect the lead to someone else
    report = client.get("/api/admin/records/verify", headers=admin_headers).json()
    assert report["ok"] is False and report["mismatches"][0]["table"] == "leads"


def test_csv_export_blocks_formula_injection(client, admin_headers):
    client.post("/api/leads", json=LEAD | {"first_name": "Ann", "comments": '=HYPERLINK("http://evil")'})
    csv_text = client.get("/api/admin/leads.csv", headers=admin_headers).text
    assert "'=HYPERLINK" in csv_text and ",=HYPERLINK" not in csv_text


# --- outbox -----------------------------------------------------------------------------------
SECRET = b"w" * 48


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_outbox(services, handler, *, fmt="json", max_attempts=3, clock=None) -> Outbox:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Outbox(services.db, http, webhook_url="https://crm.example/hook", fmt=fmt, signing_key=SECRET,
                  max_attempts=max_attempts, clock=clock or Clock())  # fmt: skip


def enqueue(services, outbox, event="lead.created", data=None, adf=None):
    with services.db.tx() as conn:
        entry = services.ledger.append(conn, event, {"x": 1})
        return outbox.enqueue(conn, event, data or {"id": "lead_1"}, entry, adf_xml=adf)


def status_of(services, delivery_id):
    with services.db.read() as conn:
        return dict(conn.execute("SELECT * FROM outbox WHERE id = ?", (delivery_id,)).fetchone())


def test_delivery_signed_and_marked(services):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    outbox = make_outbox(services, handler)
    delivery = enqueue(services, outbox)
    assert asyncio.run(outbox.process_due()) == {"delivered": 1}
    request = seen[0]
    assert request.headers["x-jim-delivery-id"] == delivery
    assert verify_signature(SECRET, request.headers["x-jim-signature"], request.content, now=outbox.clock())
    assert not verify_signature(SECRET, request.headers["x-jim-signature"], request.content + b" ", now=outbox.clock())
    assert not verify_signature(b"other" * 10, request.headers["x-jim-signature"], request.content, now=outbox.clock())
    assert json.loads(request.content)["ledger"]["seq"] >= 1
    assert status_of(services, delivery)["status"] == "delivered"


def test_signature_replay_window():
    body = b"{}"
    header = sign(SECRET, 1_000, body)
    assert verify_signature(SECRET, header, body, now=1_100)
    assert not verify_signature(SECRET, header, body, now=1_000 + 3600)
    assert not verify_signature(SECRET, "garbage", body, now=1_000)


def test_retry_backoff_then_dead_letter(services):
    clock = Clock()
    outbox = make_outbox(services, lambda r: httpx.Response(503), max_attempts=3, clock=clock)
    delivery = enqueue(services, outbox)
    ids = set()
    for _ in range(3):
        assert asyncio.run(outbox.process_due())
        row = status_of(services, delivery)
        ids.add(row["id"])
        clock.now = row["next_attempt_at"] + 1
    row = status_of(services, delivery)
    assert row["status"] == "dead" and row["attempts"] == 3 and row["last_error"] == "HTTP 503"
    assert ids == {delivery}  # the delivery id (receiver idempotency key) never changes
    assert outbox.requeue_sync(delivery) and status_of(services, delivery)["status"] == "pending"


def test_permanent_4xx_goes_dead_immediately_but_429_retries(services):
    outbox = make_outbox(services, lambda r: httpx.Response(400))
    d1 = enqueue(services, outbox)
    asyncio.run(outbox.process_due())
    assert status_of(services, d1)["status"] == "dead"
    outbox429 = make_outbox(services, lambda r: httpx.Response(429))
    d2 = enqueue(services, outbox429)
    asyncio.run(outbox429.process_due())
    assert status_of(services, d2)["status"] == "pending"


def test_network_error_is_retried(services):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    outbox = make_outbox(services, handler)
    delivery = enqueue(services, outbox)
    assert asyncio.run(outbox.process_due()) == {"retry": 1}
    assert status_of(services, delivery)["last_error"] == "ConnectError"


def test_lease_prevents_double_claim_and_expires_after_crash(services):
    clock = Clock()
    outbox = make_outbox(services, lambda r: httpx.Response(200), clock=clock)
    enqueue(services, outbox)
    first = outbox.claim_due_sync(lease_s=60)
    assert len(first) == 1
    assert outbox.claim_due_sync(lease_s=60) == []  # another worker cannot take it
    clock.now += 61  # the claiming worker "crashed"; lease expires
    assert len(outbox.claim_due_sync(lease_s=60)) == 1


def test_adf_mode_sends_xml_and_skips_non_lead_events(services):
    seen = []
    outbox = make_outbox(services, lambda r: seen.append(r) or httpx.Response(200), fmt="adf")
    enqueue(services, outbox, adf=build_adf({"id": "l1", "first_name": "Ann", "interest": "buy"}, vendor_name="JIM"))
    assert enqueue(services, outbox, event="handoff.requested") is None
    asyncio.run(outbox.process_due())
    assert seen[0].headers["content-type"] == "application/xml" and b"<adf>" in seen[0].content


def test_disabled_outbox_enqueues_nothing(services):
    assert not services.outbox.enabled
    assert enqueue(services, services.outbox) is None


def test_admin_outbox_endpoints(client):
    response = client.get("/api/admin/outbox", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200 and response.json()["enabled"] is False
    missing = client.post(
        "/api/admin/outbox/dlv_missing/requeue", json={}, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
    )
    assert missing.status_code == 404

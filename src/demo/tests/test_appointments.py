"""Scheduling: hours, lead time, holidays, DST, capacity races, abuse caps, idempotency, cancel, ICS."""

from __future__ import annotations

import multiprocessing
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from chatbot.config import DATA_DIR
from chatbot.ledger import IdempotencyConflict
from chatbot.services.appointments import BookingInput
from chatbot.services.common import ServiceError

from . import mp_workers
from .conftest import first_slot

CT = ZoneInfo("America/Chicago")
# Low-entropy fixture so secret scanners (gitleaks generic-api-key) don't mistake it for a credential.
REPLAY_ID = "booking-0000001"


def at(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=CT)


def booking(slot: datetime | str, phone="(334) 555-0142", **kw) -> BookingInput:
    data = {"department": "service", "slot_start": slot, "first_name": "Ann", "last_name": "Lee", "phone": phone,
            "consent_to_contact": True} | kw  # fmt: skip
    return BookingInput(**data)


@pytest.fixture
def appts(services):
    svc = services.appointments
    svc.clock = lambda: at(2026, 11, 9, 10, 5).astimezone(UTC)  # Monday 10:05 CST
    return svc


def labels(result):
    return [s["start"] for s in result["slots"]]


def test_lead_time_hides_near_slots(appts):
    appts.min_lead = timedelta(minutes=120)
    slots = labels(appts.availability_sync("service", date(2026, 11, 9), 1))
    assert slots[0] == "2026-11-09T12:30:00-06:00"
    assert slots[-1] == "2026-11-09T17:30:00-06:00"


def test_sunday_closed_and_saturday_hours(appts):
    appts.clock = lambda: at(2026, 11, 6, 12).astimezone(UTC)
    assert appts.availability_sync("service", date(2026, 11, 8), 1)["slots"] == []
    saturday = labels(appts.availability_sync("service", date(2026, 11, 7), 1))
    assert saturday[0] == "2026-11-07T08:00:00-06:00" and saturday[-1] == "2026-11-07T16:30:00-06:00"
    assert len(saturday) == 18


def test_thanksgiving_closed_by_default(appts):
    appts.clock = lambda: at(2026, 11, 25, 12).astimezone(UTC)
    assert appts.availability_sync("service", date(2026, 11, 26), 1)["slots"] == []


def test_dst_boundary_offsets_and_utc_storage(appts):
    appts.clock = lambda: at(2026, 10, 30, 12).astimezone(UTC)
    saturday = labels(appts.availability_sync("service", date(2026, 10, 31), 1))
    monday = labels(appts.availability_sync("service", date(2026, 11, 2), 1))
    assert saturday[0].endswith("-05:00") and monday[0].endswith("-06:00")
    first, _ = appts.book_sync(booking(saturday[0]), source="test")
    second, _ = appts.book_sync(booking(monday[0], phone="3345550143"), source="test")
    assert first["slot_start"] == "2026-10-31T13:00:00Z"  # 08:00 CDT
    assert second["slot_start"] == "2026-11-02T13:30:00Z"  # 07:30 CST


@pytest.mark.parametrize(
    ("slot", "code"),
    [
        (at(2026, 11, 10, 9, 15), "slot_invalid"),
        (at(2026, 11, 10, 6, 0), "slot_invalid"),
        (at(2026, 11, 10, 18, 0), "slot_invalid"),
        (at(2026, 11, 8, 10, 0), "slot_too_soon"),
        (at(2027, 1, 4, 10, 0), "slot_too_far"),
    ],
)
def test_bad_slots_rejected(appts, slot, code):
    with pytest.raises(ServiceError) as exc:
        appts.book_sync(booking(slot), source="test")
    assert exc.value.code == code


def test_naive_slot_means_local_time(appts):
    record, _ = appts.book_sync(booking(datetime(2026, 11, 10, 9, 0)), source="test")
    assert record["slot_start"] == "2026-11-10T15:00:00Z"


def test_capacity_enforced_and_availability_reflects_it(appts):
    slot = at(2026, 11, 10, 9)
    for i in range(3):
        appts.book_sync(booking(slot, phone=f"33455501{40 + i}"), source="test")
    with pytest.raises(ServiceError) as exc:
        appts.book_sync(booking(slot, phone="3345550199"), source="test")
    assert exc.value.code == "slot_full" and exc.value.status == 409
    assert slot.isoformat() not in labels(appts.availability_sync("service", date(2026, 11, 10), 1))


def test_per_phone_active_booking_cap(appts):
    for hour in (9, 10, 11):
        appts.book_sync(booking(at(2026, 11, 10, hour)), source="test")
    with pytest.raises(ServiceError) as exc:
        appts.book_sync(booking(at(2026, 11, 10, 12)), source="test")
    assert exc.value.code == "too_many_appointments"


def test_idempotent_replay_and_conflict(appts):
    first, replayed = appts.book_sync(booking(at(2026, 11, 10, 9)), source="test", idempotency_key="apt:k1")
    again, replayed_again = appts.book_sync(booking(at(2026, 11, 10, 9)), source="test", idempotency_key="apt:k1")
    assert not replayed and replayed_again and again["confirmation_code"] == first["confirmation_code"]
    with pytest.raises(IdempotencyConflict):
        appts.book_sync(booking(at(2026, 11, 10, 10)), source="test", idempotency_key="apt:k1")


def test_cancel_requires_matching_contact_and_frees_slot(appts):
    slot = at(2026, 11, 10, 9)
    records = [appts.book_sync(booking(slot, phone=f"33455501{50 + i}"), source="test")[0] for i in range(3)]
    code = records[0]["confirmation_code"]
    with pytest.raises(ServiceError) as wrong:
        appts.cancel_sync(code, phone_last4="0000", email=None)
    with pytest.raises(ServiceError) as unknown:
        appts.cancel_sync("ZZZZZZZZ", phone_last4="0150", email=None)
    assert wrong.value.message == unknown.value.message and wrong.value.status == unknown.value.status == 404
    assert appts.cancel_sync(code, phone_last4="0150", email=None)["already_cancelled"] is False
    assert appts.cancel_sync(code, phone_last4="0150", email=None)["already_cancelled"] is True
    assert slot.isoformat() in labels(appts.availability_sync("service", date(2026, 11, 10), 1))


def test_ics_is_rfc5545_shaped(appts):
    record, _ = appts.book_sync(booking(at(2026, 11, 10, 9), notes="Oil change, tire rotation; please"), source="test")
    ics = appts.ics(record)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "\n" not in ics.replace("\r\n", "")
    assert "DTSTART:20261110T150000Z" in ics and "DTEND:20261110T153000Z" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    assert "LOCATION:227 Eastern Blvd\\, Montgomery\\, AL 36117" in ics


def test_booking_payload_validation():
    slot = at(2026, 11, 10, 9)
    for bad in ({"consent_to_contact": False}, {"phone": "555-0142"}, {"phone": "(034) 555-0142"},
                {"last_name": "   "}, {"first_name": "R0b3rt"}, {"email": "not-an-email"}):  # fmt: skip
        with pytest.raises(ValidationError):
            booking(slot, **bad)


@pytest.mark.slow
def test_multiprocess_booking_race_never_exceeds_capacity(services):
    slot = services.appointments.availability_sync("service", None, 7)["slots"][0]["start"]
    db_path = str(services.settings.db_path)
    key = services.secrets.ledger_key
    args = [(db_path, key, str(DATA_DIR / "dealership.json"), slot, f"33455502{10 + i}") for i in range(8)]
    with multiprocessing.get_context("spawn").Pool(8) as pool:
        outcomes = pool.starmap(mp_workers.book_slot, args)
    assert sum(o.startswith("booked:") for o in outcomes) == 3
    assert sum(o == "rejected:slot_full" for o in outcomes) == 5
    with services.db.read() as conn:
        assert services.ledger.verify(conn).ok


# --- HTTP surface -------------------------------------------------------------------------------
def _body(slot: str, **kw) -> dict:
    return {"department": "service", "slot_start": slot, "first_name": "Ann", "last_name": "Lee",
            "phone": "334-555-0142", "consent_to_contact": True} | kw  # fmt: skip


def test_api_booking_flow(client):
    slot = first_slot(client)
    created = client.post("/api/appointments", json=_body(slot), headers={"Idempotency-Key": REPLAY_ID})
    assert created.status_code == 201
    data = created.json()
    assert data["phone"] == "***-***-0142" and data["ics"].startswith("BEGIN:VCALENDAR")
    replay = client.post("/api/appointments", json=_body(slot), headers={"Idempotency-Key": REPLAY_ID})
    assert replay.json()["replayed"] is True and replay.json()["confirmation_code"] == data["confirmation_code"]
    conflict = client.post(
        "/api/appointments", json=_body(slot, notes="different"), headers={"Idempotency-Key": REPLAY_ID}
    )
    assert conflict.status_code == 409 and conflict.json()["error"] == "idempotency_conflict"
    cancel = client.post(f"/api/appointments/{data['confirmation_code']}/cancel", json={"phone_last4": "0142"})
    assert cancel.status_code == 200 and cancel.json()["status"] == "cancelled"


def test_api_booking_rejections(client):
    slot = first_slot(client)
    assert client.post("/api/appointments", json=_body(slot, consent_to_contact=False)).status_code == 422
    assert client.post("/api/appointments", json=_body(slot, phone="12")).status_code == 422
    assert client.post("/api/appointments", json=_body("2020-01-01T09:00:00-06:00")).status_code == 422
    bad_key = client.post("/api/appointments", json=_body(slot), headers={"Idempotency-Key": "bad key with spaces"})
    assert bad_key.status_code == 400
    assert client.get("/api/appointments/availability", params={"department": "spa"}).status_code == 422

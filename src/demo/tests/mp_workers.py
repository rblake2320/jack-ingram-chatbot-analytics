"""Top-level functions for multi-process race tests (must be importable under 'spawn')."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def append_entries(db_path: str, key: bytes, worker: int, count: int) -> int:
    from chatbot.db import Database
    from chatbot.ledger import Ledger

    db = Database(Path(db_path))
    ledger = Ledger(key)
    for i in range(count):
        with db.tx() as conn:
            ledger.append(conn, "test.event", {"worker": worker, "i": i}, idempotency_key=f"w{worker}-{i}")
    return count


def book_slot(db_path: str, key: bytes, dealership_path: str, slot_iso: str, phone: str) -> str:
    import httpx

    from chatbot.db import Database
    from chatbot.knowledge import Knowledge
    from chatbot.ledger import Ledger
    from chatbot.services.appointments import AppointmentService, BookingInput
    from chatbot.services.common import ServiceError
    from chatbot.services.outbox import Outbox

    db = Database(Path(db_path))
    ledger = Ledger(key)
    knowledge = Knowledge(Path(dealership_path), observe_default_holidays=False)
    outbox = Outbox(db, httpx.AsyncClient(), webhook_url=None, fmt="json", signing_key=None, max_attempts=3)
    service = AppointmentService(
        db, ledger, outbox, knowledge, horizon_days=30, min_lead_minutes=0, max_active_per_phone=3
    )
    data = BookingInput(
        department="service",
        slot_start=datetime.fromisoformat(slot_iso),
        first_name="Race",
        last_name="Tester",
        phone=phone,
        consent_to_contact=True,
    )
    try:
        record, _ = service.book_sync(data, source="race")
        return "booked:" + record["confirmation_code"]
    except ServiceError as exc:
        return "rejected:" + exc.code

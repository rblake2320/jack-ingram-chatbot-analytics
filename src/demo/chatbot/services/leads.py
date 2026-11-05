"""Lead capture: validation, idempotent atomic write (row + ledger + outbox), CRM formats."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Literal

from pydantic import Field, field_validator

from ..db import Database
from ..ledger import Ledger, fingerprint, utc_now_iso
from ..text import clean_text, mask_email, mask_phone
from .adf import build_adf
from .common import ContactDetails, VehicleRef
from .outbox import Outbox

Interest = Literal["buy", "lease", "trade-in", "service", "test_drive", "general"]


class LeadInput(ContactDetails):
    interest: Interest = "general"
    vehicle: VehicleRef | None = None
    comments: str | None = Field(default=None, max_length=1000)
    preferred_contact: Literal["phone", "text", "email"] | None = None

    @field_validator("comments")
    @classmethod
    def _comments(cls, value: str | None) -> str | None:
        return clean_text(value, max_len=1000) or None if value else None


def lead_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """Canonical business record (also the input to the ledger digest)."""
    vehicle = row["vehicle"]
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "source": row["source"],
        "conversation_id": row["conversation_id"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "email": row["email"],
        "phone": row["phone"],
        "interest": row["interest"],
        "vehicle": json.loads(vehicle) if isinstance(vehicle, str) else (vehicle or {}),
        "comments": row["comments"],
        "preferred_contact": row["preferred_contact"],
        "consent": bool(row["consent"]),
    }


def public_lead(record: dict[str, Any]) -> dict[str, Any]:
    """What we echo to the customer (masked)."""
    return {
        "lead_id": record["id"],
        "first_name": record["first_name"],
        "phone": mask_phone(record["phone"]),
        "email": mask_email(record["email"]),
        "interest": record["interest"],
    }


class LeadService:
    def __init__(self, db: Database, ledger: Ledger, outbox: Outbox, *, vendor_name: str) -> None:
        self.db = db
        self.ledger = ledger
        self.outbox = outbox
        self.vendor_name = vendor_name

    def create_sync(
        self,
        data: LeadInput,
        *,
        source: str,
        conversation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        request_fp = fingerprint(data.model_dump(mode="json"))
        with self.db.tx() as conn:
            prior = self.ledger.find_idempotent(conn, idempotency_key, request_fp)
            if prior is not None:
                row = conn.execute("SELECT * FROM leads WHERE id = ?", (prior.payload["lead_id"],)).fetchone()
                return lead_record(row), True
            record = {
                "id": "lead_" + uuid.uuid4().hex[:24],
                "created_at": utc_now_iso(),
                "source": source,
                "conversation_id": conversation_id,
                "first_name": data.first_name,
                "last_name": data.last_name,
                "email": data.email,
                "phone": data.phone,
                "interest": data.interest,
                "vehicle": data.vehicle.model_dump(mode="json", exclude_none=True) if data.vehicle else {},
                "comments": data.comments,
                "preferred_contact": data.preferred_contact,
                "consent": True,
            }
            entry = self.ledger.append(
                conn,
                "lead.created",
                {
                    "lead_id": record["id"],
                    "source": source,
                    "interest": data.interest,
                    "record_digest": self.ledger.record_digest(record),
                },
                idempotency_key=idempotency_key,
                request_fp=request_fp,
            )
            conn.execute(
                "INSERT INTO leads (id, created_at, source, conversation_id, first_name, last_name, email, phone,"
                " interest, vehicle, comments, preferred_contact, consent, ledger_seq)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    record["id"], record["created_at"], source, conversation_id, record["first_name"],
                    record["last_name"], record["email"], record["phone"], record["interest"],
                    json.dumps(record["vehicle"]), record["comments"], record["preferred_contact"], entry.seq,
                ),
            )  # fmt: skip
            self.outbox.enqueue(
                conn, "lead.created", record, entry, adf_xml=build_adf(record, vendor_name=self.vendor_name)
            )
        return record, False

    async def create(self, data: LeadInput, **kwargs: Any) -> tuple[dict[str, Any], bool]:
        return await self.db.run(self.create_sync, data, **kwargs)

    def list_sync(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM leads ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [lead_record(r) | {"status": r["status"], "ledger_seq": r["ledger_seq"]} for r in rows]

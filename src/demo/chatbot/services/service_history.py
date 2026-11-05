"""Service-history lookup (VIN + last name) and DMS import.

Lookups return the SAME response for "unknown VIN" and "wrong last name" so the endpoint is
not an oracle, and are rate limited per IP and per VIN by the API layer.
"""

from __future__ import annotations

import hmac
import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..db import Database
from ..ledger import Ledger, fingerprint, utc_now_iso
from ..text import clean_text
from ..vin import validate_vin


class ServiceRecordIn(BaseModel):
    vin: str
    customer_last_name: str = Field(min_length=1, max_length=50)
    service_date: date
    mileage: int | None = Field(default=None, ge=0, le=1_000_000)
    description: str = Field(min_length=1, max_length=1000)
    ro_number: str | None = Field(default=None, max_length=40)

    @field_validator("vin")
    @classmethod
    def _vin(cls, value: str) -> str:
        check = validate_vin(value)
        if not check.valid:
            raise ValueError(check.reason)
        return check.vin

    @field_validator("customer_last_name", "description", "ro_number")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return clean_text(value, max_len=1000, multiline=False) if value else value


def _name_key(name: str) -> str:
    return "".join(ch for ch in clean_text(name).lower() if ch.isalpha())


class ServiceHistoryService:
    def __init__(self, db: Database, ledger: Ledger) -> None:
        self.db = db
        self.ledger = ledger

    def import_sync(self, records: list[ServiceRecordIn], *, source: str) -> dict[str, Any]:
        if not records:
            return {"imported": 0}
        batch = [r.model_dump(mode="json") for r in records]
        with self.db.tx() as conn:
            entry = self.ledger.append(
                conn,
                "service_records.imported",
                {"count": len(batch), "source": source, "batch_digest": self.ledger.record_digest({"records": batch})},
                idempotency_key=f"service_records.imported:{fingerprint(batch)}",
                request_fp=fingerprint(batch),
            )
            if entry.replayed:
                return {"imported": 0, "duplicate_batch": True}
            now = utc_now_iso()
            for record in batch:
                conn.execute(
                    "INSERT INTO service_records (id, vin, customer_last_name, service_date, mileage, description,"
                    " ro_number, source, created_at, ledger_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "svc_" + uuid.uuid4().hex[:20], record["vin"], record["customer_last_name"],
                        record["service_date"], record["mileage"], record["description"], record["ro_number"],
                        source, now, entry.seq,
                    ),
                )  # fmt: skip
        return {"imported": len(batch), "ledger_seq": entry.seq}

    def seed_if_empty_sync(self, path: Path) -> int:
        with self.db.read() as conn:
            if conn.execute("SELECT 1 FROM service_records LIMIT 1").fetchone():
                return 0
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        records = [ServiceRecordIn.model_validate(r) for r in raw.get("records", [])]
        return self.import_sync(records, source="sample-seed")["imported"]

    def lookup_sync(self, vin: str, last_name: str) -> dict[str, Any]:
        not_found = {"found": False, "message": "No service records matched that VIN and last name."}
        check = validate_vin(vin)
        if not check.valid or not last_name:
            return not_found
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM service_records WHERE vin = ? ORDER BY service_date DESC", (check.vin,)
            ).fetchall()
        wanted = _name_key(last_name)
        matches = [r for r in rows if hmac.compare_digest(_name_key(r["customer_last_name"]), wanted)]
        if not wanted or not matches:
            return not_found
        return {
            "found": True,
            "vin": check.vin,
            "records": [
                {
                    "service_date": r["service_date"],
                    "mileage": r["mileage"],
                    "description": r["description"],
                    "ro_number": r["ro_number"],
                }
                for r in matches[:20]
            ],
            "sample_data": any(r["source"] == "sample-seed" for r in matches),
        }

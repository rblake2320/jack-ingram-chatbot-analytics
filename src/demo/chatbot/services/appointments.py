"""Appointment scheduling (service visits and test drives).

Slots come from the department's business hours in the dealership timezone (DST-correct via
zoneinfo). Capacity is enforced inside ``BEGIN IMMEDIATE``: the count-then-insert sequence is
serialised across every process, so concurrent bookings can never exceed capacity.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..db import Database
from ..knowledge import Department, Knowledge
from ..ledger import Ledger, fingerprint, utc_now_iso
from ..text import clean_text, digits_only, mask_phone, normalize_email
from .adf import build_adf
from .common import ContactDetails, ServiceError, VehicleRef
from .outbox import Outbox

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L ambiguity
DepartmentKey = Literal["service", "test_drive"]


def _utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


class BookingInput(ContactDetails):
    department: DepartmentKey
    slot_start: datetime
    last_name: str = Field(min_length=1, max_length=50)  # required for appointments
    phone: str = Field(min_length=7, max_length=32)  # required so the store can reach the customer
    vehicle: VehicleRef | None = None
    service_type: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("service_type", "notes")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return clean_text(value, max_len=500) or None if value else None

    @model_validator(mode="after")
    def _required(self) -> BookingInput:
        if not self.last_name:
            raise ValueError("last name is required for appointments")
        if not self.phone:
            raise ValueError("a phone number is required for appointments")
        return self


class CancelInput(BaseModel):
    phone_last4: str | None = Field(default=None, min_length=4, max_length=4)
    email: str | None = Field(default=None, max_length=254)


def appointment_record(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    vehicle = row["vehicle"]
    return {
        "id": row["id"],
        "confirmation_code": row["confirmation_code"],
        "created_at": row["created_at"],
        "department": row["department"],
        "slot_start": row["slot_start"],
        "slot_end": row["slot_end"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "phone": row["phone"],
        "email": row["email"],
        "vehicle": json.loads(vehicle) if isinstance(vehicle, str) else (vehicle or {}),
        "service_type": row["service_type"],
        "notes": row["notes"],
        "conversation_id": row["conversation_id"],
        "source": row["source"],
    }


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    for ch in line:
        encoded = ch.encode("utf-8")
        if len(current) + len(encoded) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += encoded
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


class AppointmentService:
    def __init__(
        self,
        db: Database,
        ledger: Ledger,
        outbox: Outbox,
        knowledge: Knowledge,
        *,
        horizon_days: int,
        min_lead_minutes: int,
        max_active_per_phone: int,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self.db = db
        self.ledger = ledger
        self.outbox = outbox
        self.knowledge = knowledge
        self.horizon_days = horizon_days
        self.min_lead = timedelta(minutes=min_lead_minutes)
        self.max_active_per_phone = max_active_per_phone
        self.clock = clock

    def department(self, key: str) -> Department:
        try:
            return self.knowledge.departments[key]
        except KeyError as exc:
            raise ServiceError(f"Unknown department {key!r}.") from exc

    # --- slot grid ---------------------------------------------------------------------------
    def _day_slots(self, dept: Department, day: date) -> list[datetime]:
        hours = self.knowledge.day_hours(dept.hours_key, day)
        if hours is None:
            return []
        tz = self.knowledge.tz
        start = datetime.combine(day, hours.open, tzinfo=tz)
        end = datetime.combine(day, hours.close, tzinfo=tz)
        step = timedelta(minutes=dept.slot_minutes)
        slots, cursor = [], start
        while cursor + step <= end:
            slots.append(cursor)
            cursor += step
        return slots

    def _bookable_window(self) -> tuple[datetime, datetime]:
        now = self.clock()
        return now + self.min_lead, now + timedelta(days=self.horizon_days)

    def validate_slot(self, dept: Department, slot_start: datetime) -> datetime:
        if slot_start.tzinfo is None:  # naive input = dealership local time
            slot_start = slot_start.replace(tzinfo=self.knowledge.tz)
        local = slot_start.astimezone(self.knowledge.tz)
        earliest, latest = self._bookable_window()
        if local < earliest:
            raise ServiceError("That time is too soon or in the past; please pick a later slot.", code="slot_too_soon")
        if local > latest:
            raise ServiceError(f"We book up to {self.horizon_days} days ahead.", code="slot_too_far")
        if local not in self._day_slots(dept, local.date()):
            raise ServiceError("That is not an available appointment time.", code="slot_invalid")
        return local

    def availability_sync(self, dept_key: str, start: date | None = None, days: int = 3) -> dict[str, Any]:
        dept = self.department(dept_key)
        days = max(1, min(days, 14))
        earliest, latest = self._bookable_window()
        first_day = max(
            start or earliest.astimezone(self.knowledge.tz).date(), earliest.astimezone(self.knowledge.tz).date()
        )
        candidates: list[datetime] = []
        for offset in range(days):
            day = first_day + timedelta(days=offset)
            candidates.extend(s for s in self._day_slots(dept, day) if earliest <= s <= latest)
        if not candidates:
            return {"department": dept.key, "label": dept.label, "slots": [], "timezone": str(self.knowledge.tz)}
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT slot_start, COUNT(*) AS n FROM appointments WHERE department = ? AND status = 'booked'"
                " AND slot_start BETWEEN ? AND ? GROUP BY slot_start",
                (dept.key, _utc_iso(candidates[0]), _utc_iso(candidates[-1])),
            ).fetchall()
        booked = {r["slot_start"]: r["n"] for r in rows}
        slots = []
        for slot in candidates:
            remaining = dept.capacity - booked.get(_utc_iso(slot), 0)
            if remaining > 0:
                slots.append(
                    {
                        "start": slot.isoformat(),
                        "label": slot.strftime("%a %b %d, %I:%M %p").replace(" 0", " "),
                        "remaining": remaining,
                    }
                )
        return {"department": dept.key, "label": dept.label, "timezone": str(self.knowledge.tz), "slots": slots}

    async def availability(self, dept_key: str, start: date | None = None, days: int = 3) -> dict[str, Any]:
        return await self.db.run(self.availability_sync, dept_key, start, days)

    # --- booking -----------------------------------------------------------------------------
    def _new_code(self, conn: sqlite3.Connection) -> str:
        for _ in range(10):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            if conn.execute("SELECT 1 FROM appointments WHERE confirmation_code = ?", (code,)).fetchone() is None:
                return code
        raise RuntimeError("could not allocate a confirmation code")

    def book_sync(
        self,
        data: BookingInput,
        *,
        source: str,
        conversation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        dept = self.department(data.department)
        local_start = self.validate_slot(dept, data.slot_start)
        slot_start = _utc_iso(local_start)
        slot_end = _utc_iso(local_start + timedelta(minutes=dept.slot_minutes))
        request_fp = fingerprint(data.model_dump(mode="json") | {"slot_start": slot_start})
        with self.db.tx() as conn:
            prior = self.ledger.find_idempotent(conn, idempotency_key, request_fp)
            if prior is not None:
                row = conn.execute(
                    "SELECT * FROM appointments WHERE id = ?", (prior.payload["appointment_id"],)
                ).fetchone()
                return appointment_record(row), True
            taken = conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE department = ? AND slot_start = ? AND status = 'booked'",
                (dept.key, slot_start),
            ).fetchone()[0]
            if taken >= dept.capacity:
                raise ServiceError(
                    "Sorry, that time was just booked. Please choose another slot.", code="slot_full", status=409
                )
            active = conn.execute(
                "SELECT COUNT(*) FROM appointments WHERE phone = ? AND status = 'booked' AND slot_start > ?",
                (data.phone, _utc_iso(self.clock())),
            ).fetchone()[0]
            if active >= self.max_active_per_phone:
                raise ServiceError(
                    "This phone number already has the maximum number of upcoming appointments.",
                    code="too_many_appointments",
                    status=409,
                )
            record = {
                "id": "apt_" + uuid.uuid4().hex[:24],
                "confirmation_code": self._new_code(conn),
                "created_at": utc_now_iso(),
                "department": dept.key,
                "slot_start": slot_start,
                "slot_end": slot_end,
                "first_name": data.first_name,
                "last_name": data.last_name,
                "phone": data.phone,
                "email": data.email,
                "vehicle": data.vehicle.model_dump(mode="json", exclude_none=True) if data.vehicle else {},
                "service_type": data.service_type,
                "notes": data.notes,
                "conversation_id": conversation_id,
                "source": source,
            }
            entry = self.ledger.append(
                conn,
                "appointment.booked",
                {
                    "appointment_id": record["id"],
                    "department": dept.key,
                    "slot_start": slot_start,
                    "record_digest": self.ledger.record_digest(record),
                },
                idempotency_key=idempotency_key,
                request_fp=request_fp,
            )
            conn.execute(
                "INSERT INTO appointments (id, confirmation_code, created_at, department, slot_start, slot_end, status,"
                " first_name, last_name, phone, email, vehicle, service_type, notes, conversation_id, source, ledger_seq)"
                " VALUES (?, ?, ?, ?, ?, ?, 'booked', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"], record["confirmation_code"], record["created_at"], dept.key, slot_start, slot_end,
                    record["first_name"], record["last_name"], record["phone"], record["email"],
                    json.dumps(record["vehicle"]), record["service_type"], record["notes"], conversation_id, source,
                    entry.seq,
                ),
            )  # fmt: skip
            local_label = local_start.strftime("%A %B %d at %I:%M %p %Z")
            adf_lead = record | {
                "interest": "test_drive" if dept.key == "test_drive" else "service",
                "comments": data.notes,
                "appointment_summary": f"{dept.label} booked for {local_label} (confirmation {record['confirmation_code']})",
            }
            self.outbox.enqueue(
                conn, "appointment.booked", record, entry, adf_xml=build_adf(adf_lead, vendor_name=self.knowledge.name)
            )
        return record, False

    async def book(self, data: BookingInput, **kwargs: Any) -> tuple[dict[str, Any], bool]:
        return await self.db.run(self.book_sync, data, **kwargs)

    def cancel_sync(self, code: str, *, phone_last4: str | None, email: str | None) -> dict[str, Any]:
        code = (code or "").strip().upper()
        not_found = ServiceError("No matching appointment was found.", code="not_found", status=404)
        if not code or len(code) > 12 or (not phone_last4 and not email):
            raise not_found
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM appointments WHERE confirmation_code = ?", (code,)).fetchone()
            if row is None:
                raise not_found
            phone_ok = bool(phone_last4) and digits_only(row["phone"])[-4:] == digits_only(phone_last4 or "")
            email_ok = bool(email) and row["email"] is not None and normalize_email(email or "") == row["email"]
            if not (phone_ok or email_ok):
                raise not_found  # identical response: no oracle for valid codes
            if row["status"] == "cancelled":
                return {"confirmation_code": code, "status": "cancelled", "already_cancelled": True}
            entry = self.ledger.append(
                conn,
                "appointment.cancelled",
                {"appointment_id": row["id"], "confirmation_code": code},
                idempotency_key=f"appointment.cancelled:{row['id']}",
            )
            conn.execute(
                "UPDATE appointments SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
                (utc_now_iso(), row["id"]),
            )
            self.outbox.enqueue(
                conn, "appointment.cancelled", {"appointment_id": row["id"], "confirmation_code": code}, entry
            )
        return {"confirmation_code": code, "status": "cancelled", "already_cancelled": False}

    def public_view(self, record: dict[str, Any]) -> dict[str, Any]:
        dept = self.department(record["department"])
        local = _parse_utc(record["slot_start"]).astimezone(self.knowledge.tz)
        return {
            "confirmation_code": record["confirmation_code"],
            "department": dept.key,
            "label": dept.label,
            "start": local.isoformat(),
            "start_label": local.strftime("%A, %B %d at %I:%M %p %Z").replace(" 0", " "),
            "name": f"{record['first_name']} {record['last_name']}",
            "phone": mask_phone(record["phone"]),
            "ics": self.ics(record),
        }

    def ics(self, record: dict[str, Any]) -> str:
        dept = self.department(record["department"])
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        start = record["slot_start"].replace("-", "").replace(":", "")
        end = record["slot_end"].replace("-", "").replace(":", "")
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Jack Ingram Motors//AI Assistant//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{record['id']}@jackingram-assistant",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            "SUMMARY:" + _ics_escape(f"{dept.label} - {self.knowledge.name}"),
            "LOCATION:" + _ics_escape(self.knowledge.data["main_address"]),
            "DESCRIPTION:" + _ics_escape(f"Confirmation {record['confirmation_code']}."),
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        return "\r\n".join(_fold(line) for line in lines) + "\r\n"

    def list_sync(self, *, start: str | None = None, end: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE slot_start >= ? AND slot_start <= ? ORDER BY slot_start LIMIT ?",
                (start or "0000", end or "9999", limit),
            ).fetchall()
        return [appointment_record(r) | {"status": r["status"]} for r in rows]

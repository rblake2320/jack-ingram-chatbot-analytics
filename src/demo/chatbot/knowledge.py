"""Dealership facts and business-hours logic (single source: dealership.json)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HOURS_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")

BRAND_ALIASES = {
    "audi": "Audi",
    "mercedes": "Mercedes-Benz",
    "mercedes-benz": "Mercedes-Benz",
    "mercedes benz": "Mercedes-Benz",
    "benz": "Mercedes-Benz",
    "mb": "Mercedes-Benz",
    "nissan": "Nissan",
    "porsche": "Porsche",
    "volkswagen": "Volkswagen",
    "vw": "Volkswagen",
    "volvo": "Volvo",
}


def canonical_brand(raw: str | None) -> str | None:
    if not raw:
        return None
    return BRAND_ALIASES.get(raw.strip().lower(), raw.strip())


@dataclass(frozen=True)
class DayHours:
    open: time
    close: time


@dataclass(frozen=True)
class Department:
    key: str
    label: str
    hours_key: str
    slot_minutes: int
    capacity: int


def _parse_hours(spec: str | None) -> DayHours | None:
    if spec is None:
        return None
    match = _HOURS_RE.match(spec)
    if not match:
        raise ValueError(f"bad hours spec {spec!r}; expected HH:MM-HH:MM")
    h1, m1, h2, m2 = (int(x) for x in match.groups())
    opening, closing = time(h1, m1), time(h2, m2)
    if closing <= opening:
        raise ValueError(f"closing time must be after opening: {spec!r}")
    return DayHours(opening, closing)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def default_holidays(year: int) -> set[date]:
    """New Year's Day, Thanksgiving (4th Thursday of November), Christmas Day."""
    return {date(year, 1, 1), _nth_weekday(year, 11, 3, 4), date(year, 12, 25)}


class Knowledge:
    def __init__(
        self,
        path: Path,
        *,
        timezone: str = "America/Chicago",
        closed_dates: list[date] | None = None,
        observe_default_holidays: bool = True,
    ) -> None:
        self.data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        self.tz = ZoneInfo(timezone)
        self.closed_dates = set(closed_dates or [])
        self.observe_default_holidays = observe_default_holidays
        self.hours: dict[str, dict[int, DayHours | None]] = {}
        for dept, table in self.data["hours"].items():
            self.hours[dept] = {i: _parse_hours(table.get(key)) for i, key in enumerate(DAY_KEYS)}
        self.departments: dict[str, Department] = {}
        for key, spec in self.data["departments"].items():
            if spec["hours"] not in self.hours:
                raise ValueError(f"department {key} references unknown hours table {spec['hours']}")
            self.departments[key] = Department(
                key=key,
                label=spec["label"],
                hours_key=spec["hours"],
                slot_minutes=int(spec["slot_minutes"]),
                capacity=int(spec["capacity"]),
            )

    # --- facts -----------------------------------------------------------------------------
    @property
    def verified(self) -> bool:
        return bool(self.data.get("_meta", {}).get("verified"))

    @property
    def name(self) -> str:
        return self.data["group_name"]

    @property
    def brands(self) -> list[str]:
        return list(self.data["brands"])

    def store(self, brand: str | None) -> dict[str, Any] | None:
        brand = canonical_brand(brand)
        for store in self.data["stores"]:
            if store["brand"] == brand:
                return store
        return None

    def public_info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "city": self.data["city"],
            "website": self.data["website"],
            "main_address": self.data["main_address"],
            "brands": self.brands,
            "stores": [{k: v for k, v in s.items() if k not in ("tone",)} for s in self.data["stores"]],
            "hours": self.data["hours"],
            "hours_note": self.data.get("hours_note"),
            "services": self.data["services"],
            "verified": self.verified,
        }

    def hours_text(self, dept: str) -> str:
        """Compact weekly hours, grouping consecutive days with identical hours (Mon-Fri ...)."""
        table = self.hours[dept]
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        groups: list[tuple[int, int, DayHours | None]] = []
        for i in range(7):
            if groups and groups[-1][2] == table[i]:
                groups[-1] = (groups[-1][0], i, table[i])
            else:
                groups.append((i, i, table[i]))
        parts = []
        for first, last, day in groups:
            span = labels[first] if first == last else f"{labels[first]}-{labels[last]}"
            parts.append(f"{span} {_fmt(day.open)}-{_fmt(day.close)}" if day else f"{span} closed")
        return ", ".join(parts)

    def facts_block(self) -> str:
        """Static facts for the system prompt (frozen per deploy)."""
        lines = [
            f"Dealership group: {self.name}, {self.data['city']}. Website: {self.data['website']}",
            f"Main address: {self.data['main_address']}",
            "Brands: " + ", ".join(self.brands),
            "Sales hours: " + self.hours_text("sales"),
            "Service hours: " + self.hours_text("service"),
        ]
        if self.data.get("hours_note"):
            lines.append("Hours note: " + self.data["hours_note"])
        for store in self.data["stores"]:
            bits = [store["name"]]
            if store.get("address"):
                bits.append(store["address"])
            if store.get("sales_phone"):
                bits.append(f"sales {store['sales_phone']}")
            if store.get("service_phone"):
                bits.append(f"service {store['service_phone']}")
            bits.append(f"tone: {store['tone']}")
            lines.append("- " + "; ".join(bits))
        lines.append("Sales services: " + ", ".join(self.data["services"]["sales"]))
        lines.append("Service department: " + ", ".join(self.data["services"]["service"]))
        if not self.verified:
            lines.append(
                "VERIFICATION STATUS: these facts have not been re-confirmed with the dealership. "
                "When giving hours, addresses or phone numbers, add a short note to confirm by phone or on the website."
            )
        return "\n".join(lines)

    # --- business hours ----------------------------------------------------------------------
    def is_closed_date(self, day: date) -> bool:
        if day in self.closed_dates:
            return True
        return self.observe_default_holidays and day in default_holidays(day.year)

    def day_hours(self, hours_key: str, day: date) -> DayHours | None:
        if self.is_closed_date(day):
            return None
        return self.hours[hours_key][day.weekday()]

    def is_open(self, hours_key: str, moment: datetime) -> bool:
        local = moment.astimezone(self.tz)
        hours = self.day_hours(hours_key, local.date())
        return bool(hours and hours.open <= local.time() < hours.close)

    def next_opening(self, hours_key: str, moment: datetime, *, max_days: int = 14) -> datetime | None:
        local = moment.astimezone(self.tz)
        for offset in range(max_days + 1):
            day = local.date() + timedelta(days=offset)
            hours = self.day_hours(hours_key, day)
            if not hours:
                continue
            opening = datetime.combine(day, hours.open, tzinfo=self.tz)
            closing = datetime.combine(day, hours.close, tzinfo=self.tz)
            if offset == 0 and local >= closing:
                continue
            return max(opening, local) if offset == 0 else opening
        return None

    def now(self) -> datetime:
        return datetime.now(self.tz)


def _fmt(t: time) -> str:
    hour = t.hour % 12 or 12
    suffix = "AM" if t.hour < 12 else "PM"
    return f"{hour}:{t.minute:02d} {suffix}"

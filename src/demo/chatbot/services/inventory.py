"""Inventory feed: validated load, search, comparison and price context.

The bundled feed is SAMPLE data (``_meta.sample = true``) and every API/tool response carries
``is_sample`` so the assistant tells customers so. Point INVENTORY_FEED_PATH at a DMS export
in the same schema for live inventory; invalid rows are skipped and counted, never fatal.
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..knowledge import canonical_brand

log = logging.getLogger(__name__)

Condition = Literal["new", "used", "cpo"]
SortKey = Literal["price_asc", "price_desc", "year_desc", "mileage_asc", "relevance"]
COMPARE_FIELDS = (
    "condition", "year", "make", "model", "trim", "body_style", "price", "msrp", "mileage", "fuel_type",
    "drivetrain", "transmission", "engine", "mpg_city", "mpg_highway", "exterior_color", "interior_color",
)  # fmt: skip


class Vehicle(BaseModel):
    stock_number: str = Field(min_length=1, max_length=20)
    vin: str = Field(min_length=17, max_length=17)
    condition: Condition
    year: int = Field(ge=1980, le=2100)
    make: str
    model: str
    trim: str | None = None
    body_style: str
    exterior_color: str | None = None
    interior_color: str | None = None
    mileage: int = Field(ge=0, le=1_000_000)
    price: int = Field(gt=0, le=5_000_000)
    msrp: int | None = Field(default=None, gt=0)
    fuel_type: str
    drivetrain: str | None = None
    transmission: str | None = None
    engine: str | None = None
    mpg_city: int | None = None
    mpg_highway: int | None = None
    features: list[str] = Field(default_factory=list)
    status: Literal["available", "in_transit", "pending_sale", "sold"] = "available"
    store: str | None = None

    @field_validator("make")
    @classmethod
    def _brand(cls, value: str) -> str:
        return canonical_brand(value) or value

    @field_validator("stock_number", "vin")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()

    def haystack(self) -> str:
        parts = [self.make, self.model, self.trim or "", self.body_style, self.fuel_type, self.condition,
                 self.exterior_color or "", self.drivetrain or "", " ".join(self.features)]  # fmt: skip
        return " ".join(parts).lower()

    def summary(self) -> dict[str, Any]:
        return self.model_dump(exclude={"features"}) | {"features": self.features[:8]}


class Offer(BaseModel):
    id: str
    brand: str
    title: str
    description: str
    models: list[str] = Field(default_factory=list)
    expires: date

    @field_validator("brand")
    @classmethod
    def _brand(cls, value: str) -> str:
        return canonical_brand(value) or value


class SearchFilters(BaseModel):
    make: str | None = None
    model: str | None = None
    body_style: str | None = None
    condition: Condition | None = None
    fuel_type: str | None = None
    min_year: int | None = Field(default=None, ge=1980, le=2100)
    max_year: int | None = Field(default=None, ge=1980, le=2100)
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    max_mileage: int | None = Field(default=None, ge=0)
    query: str | None = Field(default=None, max_length=100)
    sort: SortKey = "relevance"
    limit: int = Field(default=6, ge=1, le=20)
    include_unavailable: bool = False


class InventoryRepository:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.vehicles: dict[str, Vehicle] = {}
        self.offers: list[Offer] = []
        self.meta: dict[str, Any] = {}
        self.skipped = 0
        self.load()

    def load(self) -> dict[str, Any]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        vehicles: dict[str, Vehicle] = {}
        skipped = 0
        for row in raw.get("vehicles", []):
            try:
                vehicle = Vehicle.model_validate(row)
            except ValidationError:
                skipped += 1
                continue
            vehicles[vehicle.stock_number] = vehicle
        offers = []
        for row in raw.get("offers", []):
            try:
                offers.append(Offer.model_validate(row))
            except ValidationError:
                skipped += 1
        with self._lock:  # atomic swap; readers never see a half-loaded feed
            self.vehicles, self.offers, self.meta, self.skipped = vehicles, offers, raw.get("_meta", {}), skipped
        if skipped:
            log.warning("inventory feed: skipped %d invalid rows", skipped)
        return {"vehicles": len(vehicles), "offers": len(offers), "skipped": skipped}

    @property
    def is_sample(self) -> bool:
        return bool(self.meta.get("sample", False))

    def _notice(self) -> dict[str, Any]:
        out: dict[str, Any] = {"is_sample": self.is_sample}
        if self.is_sample:
            out["notice"] = "Sample listings for demonstration; not live dealership inventory."
        return out

    def get(self, stock_number: str) -> Vehicle | None:
        return self.vehicles.get((stock_number or "").strip().upper())

    def search(self, filters: SearchFilters) -> dict[str, Any]:
        make = canonical_brand(filters.make)
        tokens = [t for t in (filters.query or "").lower().split() if len(t) > 1]
        results: list[tuple[int, Vehicle]] = []
        for vehicle in list(self.vehicles.values()):
            if not filters.include_unavailable and vehicle.status not in ("available", "in_transit"):
                continue
            if make and vehicle.make.lower() != make.lower():
                continue
            if filters.model and filters.model.lower() not in vehicle.model.lower():
                continue
            if filters.body_style and filters.body_style.lower() not in vehicle.body_style.lower():
                continue
            if filters.condition and vehicle.condition != filters.condition:
                continue
            if filters.fuel_type and filters.fuel_type.lower() not in vehicle.fuel_type.lower():
                continue
            if filters.min_year and vehicle.year < filters.min_year:
                continue
            if filters.max_year and vehicle.year > filters.max_year:
                continue
            if filters.min_price is not None and vehicle.price < filters.min_price:
                continue
            if filters.max_price is not None and vehicle.price > filters.max_price:
                continue
            if filters.max_mileage is not None and vehicle.mileage > filters.max_mileage:
                continue
            hay = vehicle.haystack()
            score = sum(1 for t in tokens if t in hay)
            if tokens and score == 0:
                continue
            results.append((score, vehicle))
        sorters = {
            "price_asc": lambda sv: (sv[1].price,),
            "price_desc": lambda sv: (-sv[1].price,),
            "year_desc": lambda sv: (-sv[1].year, sv[1].price),
            "mileage_asc": lambda sv: (sv[1].mileage, sv[1].price),
            "relevance": lambda sv: (-sv[0], sv[1].price),
        }
        results.sort(key=sorters[filters.sort])
        return {
            "total": len(results),
            "vehicles": [v.summary() for _, v in results[: filters.limit]],
            **self._notice(),
        }

    def price_context(self, vehicle: Vehicle) -> dict[str, Any]:
        peers = [
            v.price
            for v in self.vehicles.values()
            if v.make == vehicle.make
            and v.model == vehicle.model
            and abs(v.year - vehicle.year) <= 1
            and v.condition == vehicle.condition
            and v.status != "sold"
        ]
        context: dict[str, Any] = {"comparable_units": len(peers)}
        if len(peers) >= 2:
            context.update(
                min_price=min(peers),
                median_price=int(statistics.median(peers)),
                max_price=max(peers),
                percentile=round(100 * sum(1 for p in peers if p < vehicle.price) / (len(peers) - 1)),
            )
        if vehicle.msrp:
            context["below_msrp"] = vehicle.msrp - vehicle.price
        return context

    def compare(self, stock_numbers: list[str]) -> dict[str, Any]:
        unique = list(dict.fromkeys(s.strip().upper() for s in stock_numbers if s and s.strip()))
        if not 2 <= len(unique) <= 4:
            raise ValueError("Compare between 2 and 4 different stock numbers.")
        vehicles = [self.get(s) for s in unique]
        missing = [s for s, v in zip(unique, vehicles, strict=True) if v is None]
        if missing:
            raise ValueError("Unknown stock number(s): " + ", ".join(missing))
        found = [v for v in vehicles if v is not None]
        differences = {}
        for field_name in COMPARE_FIELDS:
            values = [getattr(v, field_name) for v in found]
            if len({json.dumps(x) for x in values}) > 1:
                differences[field_name] = values
        return {
            "vehicles": [v.summary() | {"price_context": self.price_context(v)} for v in found],
            "differences": differences,
            "lowest_price": min(found, key=lambda v: v.price).stock_number,
            **self._notice(),
        }

    def current_offers(self, make: str | None = None, *, today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        brand = canonical_brand(make)
        offers = [
            o.model_dump(mode="json")
            for o in self.offers
            if o.expires >= today and (brand is None or o.brand.lower() == brand.lower())
        ]
        return {"offers": offers, **self._notice()}

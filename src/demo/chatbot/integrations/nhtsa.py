"""NHTSA public APIs (no key required): vPIC VIN decoding, recalls, NCAP safety ratings.

Parsing is deliberately tolerant (case-insensitive keys, missing fields -> None) because the
public schemas have changed field casing before (``results`` vs ``Results``).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from ..cache import Cache
from ..resilience import CircuitBreaker, UpstreamError, request_json
from ..vin import validate_vin

_NAME_RE = re.compile(r"^[A-Za-z0-9 .&'\-]{1,40}$")
_EMPTY = {"", "not applicable", "null", "none", "n/a"}

DECODE_TTL = 30 * 86400
RECALL_TTL = 12 * 3600
RATINGS_TTL = 7 * 86400


def _ci(record: Any, *names: str) -> Any:
    if not isinstance(record, dict):
        return None
    lower = {str(k).lower(): v for k, v in record.items()}
    for name in names:
        value = lower.get(name.lower())
        if isinstance(value, str):
            value = value.strip()
            if value.lower() in _EMPTY:
                value = None
        if value not in (None, ""):
            return value
    return None


def _clip(text: Any, limit: int = 600) -> Any:
    if isinstance(text, str) and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _check_name(field: str, value: str) -> str:
    value = (value or "").strip()
    if not _NAME_RE.match(value):
        raise ValueError(f"{field} contains unsupported characters")
    return value


class NhtsaClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        cache: Cache,
        *,
        vpic_base: str,
        api_base: str,
        enabled: bool = True,
        sleep=None,
    ) -> None:
        self.http = http
        self.cache = cache
        self.vpic_base = vpic_base.rstrip("/")
        self.api_base = api_base.rstrip("/")
        self.enabled = enabled
        self.breaker = CircuitBreaker("nhtsa")
        self._sleep_kw = {"sleep": sleep} if sleep else {}

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if not self.enabled:
            raise UpstreamError("nhtsa", "not_configured")
        return await request_json(
            self.http, "GET", url, upstream="nhtsa", breaker=self.breaker, params=params, **self._sleep_kw
        )

    async def decode_vin(self, raw_vin: str) -> dict[str, Any]:
        check = validate_vin(raw_vin)
        if not check.valid:
            raise ValueError(check.reason)
        key = f"nhtsa:vpic:{check.vin}"
        cached = await self.cache.get(key)
        if cached is not None:
            return cached
        data = await self._get(f"{self.vpic_base}/vehicles/DecodeVinValues/{check.vin}", {"format": "json"})
        results = _ci(data, "Results") or []
        row = results[0] if results else {}
        decoded = {
            "vin": check.vin,
            "year": _ci(row, "ModelYear"),
            "make": _ci(row, "Make"),
            "model": _ci(row, "Model"),
            "trim": _ci(row, "Trim"),
            "series": _ci(row, "Series"),
            "body_class": _ci(row, "BodyClass"),
            "vehicle_type": _ci(row, "VehicleType"),
            "drive_type": _ci(row, "DriveType"),
            "fuel_type": _ci(row, "FuelTypePrimary"),
            "electrification": _ci(row, "ElectrificationLevel"),
            "engine_cylinders": _ci(row, "EngineCylinders"),
            "displacement_l": _ci(row, "DisplacementL"),
            "engine_hp": _ci(row, "EngineHP"),
            "transmission": _ci(row, "TransmissionStyle"),
            "doors": _ci(row, "Doors"),
            "manufacturer": _ci(row, "Manufacturer"),
            "plant_country": _ci(row, "PlantCountry"),
            "nhtsa_error_code": _ci(row, "ErrorCode"),
            "nhtsa_message": _clip(_ci(row, "ErrorText"), 300),
            "source": "NHTSA vPIC",
        }
        decoded["decoded"] = bool(decoded["make"] and decoded["year"])
        await self.cache.set(key, decoded, DECODE_TTL)
        return decoded

    async def recalls(self, make: str, model: str, year: int) -> dict[str, Any]:
        make, model = _check_name("make", make), _check_name("model", model)
        if not 1950 <= int(year) <= 2100:
            raise ValueError("model year out of range")
        key = f"nhtsa:recalls:{make.lower()}:{model.lower()}:{year}"
        cached = await self.cache.get(key)
        if cached is not None:
            return cached
        data = await self._get(
            f"{self.api_base}/recalls/recallsByVehicle", {"make": make, "model": model, "modelYear": int(year)}
        )
        items = _ci(data, "results") or []
        recalls = [
            {
                "campaign": _ci(r, "NHTSACampaignNumber"),
                "component": _ci(r, "Component"),
                "summary": _clip(_ci(r, "Summary")),
                "consequence": _clip(_ci(r, "Consequence")),
                "remedy": _clip(_ci(r, "Remedy")),
                "report_date": _ci(r, "ReportReceivedDate"),
                "park_it": bool(_ci(r, "parkIt")),
                "park_outside": bool(_ci(r, "parkOutSide")),
            }
            for r in items[:25]
            if isinstance(r, dict)
        ]
        result = {
            "make": make,
            "model": model,
            "year": int(year),
            "count": len(recalls),
            "recalls": recalls,
            "source": "NHTSA recalls API",
            "note": "Recalls listed by make/model/year. Whether a specific VIN still needs the remedy must be"
            " confirmed by the service department or at nhtsa.gov/recalls.",
        }
        await self.cache.set(key, result, RECALL_TTL)
        return result

    async def safety_ratings(self, make: str, model: str, year: int) -> dict[str, Any]:
        make, model = _check_name("make", make), _check_name("model", model)
        if not 1990 <= int(year) <= 2100:
            raise ValueError("model year out of range")
        key = f"nhtsa:ratings:{make.lower()}:{model.lower()}:{year}"
        cached = await self.cache.get(key)
        if cached is not None:
            return cached
        variants = await self._get(
            f"{self.api_base}/SafetyRatings/modelyear/{int(year)}/make/{quote(make, safe='')}"
            f"/model/{quote(model, safe='')}"
        )
        vehicles = []
        for variant in (_ci(variants, "Results") or [])[:3]:
            vehicle_id = _ci(variant, "VehicleId")
            if vehicle_id is None:
                continue
            detail = await self._get(f"{self.api_base}/SafetyRatings/VehicleId/{int(vehicle_id)}")
            rows = _ci(detail, "Results") or [{}]
            row = rows[0] if rows else {}
            vehicles.append(
                {
                    "description": _ci(row, "VehicleDescription") or _ci(variant, "VehicleDescription"),
                    "overall": _ci(row, "OverallRating"),
                    "frontal_crash": _ci(row, "OverallFrontCrashRating"),
                    "side_crash": _ci(row, "OverallSideCrashRating"),
                    "rollover": _ci(row, "RolloverRating", "RollOverRating"),
                }
            )
        result = {"make": make, "model": model, "year": int(year), "vehicles": vehicles, "source": "NHTSA NCAP"}
        await self.cache.set(key, result, RATINGS_TTL)
        return result

"""Bounded official NHTSA model-year lookup; never a VIN clearance or diagnosis."""

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .knowledge_base import LOCATIONS

VEHICLES = {
    "porsche-911": ("PORSCHE", "911", "porsche"),
    "vw-atlas": ("VOLKSWAGEN", "ATLAS", "volkswagen"),
    "nissan-rogue": ("NISSAN", "ROGUE", "nissan"),
    "nissan-pathfinder": ("NISSAN", "PATHFINDER", "nissan"),
    "audi-q5": ("AUDI", "Q5", "audi"),
    "volvo-xc90": ("VOLVO", "XC90", "volvo"),
    "mercedes-glc": ("MERCEDES-BENZ", "GLC300", "mercedes"),
}
SNAPSHOTS = json.loads((Path(__file__).parent / "data/recall_snapshots.json").read_text(encoding="utf-8"))
_cache, _lock = {}, threading.Lock()


def lookup(vehicle, year):
    if vehicle not in VEHICLES or type(year) is not int or not 2019 <= year <= 2027:
        raise ValueError("Choose a supported vehicle and a year from 2019 to 2027")
    make, model, _ = VEHICLES[vehicle]
    key = f"{vehicle}:{year}"
    url = "https://api.nhtsa.gov/recalls/recallsByVehicle?" + urlencode(
        {"make": make, "model": model, "modelYear": year}
    )
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 600:
            return cached[1]
        result = {
            "vehicle": vehicle,
            "year": year,
            "make": make,
            "model": model,
            "source_url": url,
            "vin_verified": False,
            "recalls": [],
        }
        try:
            with httpx.Client(timeout=8, follow_redirects=False) as client:
                with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 2_000_000:
                            raise ValueError("NHTSA response exceeds size limit")
            data = json.loads(content)
            rows = data.get("results")
            if (
                not isinstance(rows, list)
                or len(rows) > 100
                or not all(isinstance(row, dict) for row in rows)
                or data.get("Count", data.get("count")) != len(rows)
            ):
                raise ValueError("NHTSA returned an invalid results envelope")
            if any(
                any(
                    not isinstance(r.get(field), str) or len(r[field]) > 30_000
                    for field in (
                        "Make",
                        "Model",
                        "NHTSACampaignNumber",
                        "Component",
                        "Summary",
                        "Consequence",
                        "Remedy",
                    )
                )
                or str(r.get("ModelYear")) != str(year)
                or r.get("Make", "").upper() != make
                or r.get("Model", "").upper() != model
                for r in rows
            ):
                raise ValueError("NHTSA returned a different vehicle")
            checked = datetime.now(timezone.utc).isoformat()
            cards = [card(row, vehicle, year, checked) for row in rows]
            result.update(status="live", checked_at=checked, recalls=rows, cards=cards)
        except (httpx.HTTPError, ValueError, TypeError) as error:
            snapshot = SNAPSHOTS.get(key)
            result.update(
                status="saved_snapshot" if snapshot else "unavailable",
                checked_at=snapshot["checked_at"] if snapshot else None,
                recalls=snapshot["recalls"] if snapshot else [],
                error="Official live lookup could not be completed. This is not a no-recall result.",
                upstream_http_status=error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else None,
            )
        result["cards"] = [card(row, vehicle, year, result["checked_at"]) for row in result["recalls"]]
        _cache[key] = (time.monotonic(), result)
        return result


def card(row, vehicle, year, checked_at):
    campaign = row.get("NHTSACampaignNumber", "")
    if not re.fullmatch(r"\d{2}V\d{6}", campaign):
        raise ValueError("Invalid campaign identifier")
    component = row.get("Component", "")
    modeled = None
    if vehicle == "porsche-911":
        modeled = {"25V896000": "rear-camera", "25V079000": "front-lighting"}.get(campaign)
    return {
        "campaign": campaign,
        "title": component,
        "year": year,
        "summary": row.get("Summary", ""),
        "consequence": row.get("Consequence", ""),
        "remedy": row.get("Remedy", ""),
        "do_not_drive": row.get("parkIt") is True,
        "park_outside": row.get("parkOutSide") is True,
        "checked_at": checked_at,
        "official_url": "https://www.nhtsa.gov/recalls?nhtsaId=" + campaign,
        "vin_url": "https://www.nhtsa.gov/recalls",
        "component_id": modeled,
        "explorer_url": "/vehicle-atlas?subject=systems&recall=" + campaign + "&year=" + str(year)
        if modeled
        else None,
        "model_scope": f"{year} {VEHICLES[vehicle][0]} {VEHICLES[vehicle][1]} model-level campaign. Confirm your VIN and repair status with NHTSA or the manufacturer.",
        "geometry_scope": "2026 representative component region; this does not apply the campaign to a 2026 vehicle."
        if modeled and year != 2026
        else None,
    }


def advise_recall(message, context=None, history=None):
    text = message.lower()
    previous = [row.get("content", "").lower() for row in (history or [])[-4:] if row.get("role") == "user"]
    if (
        not re.search(r"\b(recall|recalls|\d{2}v\d{6})\b", text)
        and re.search(r"\b20\d{2}\b", text)
        and previous
        and "recall" in previous[-1]
    ):
        text = previous[-1] + " " + text
    if not re.search(r"\b(recall|recalls|\d{2}v\d{6})\b", text):
        return None
    year_match = re.search(r"\b(20\d{2})\b", text)
    campaign_match = re.search(r"\b(\d{2}v\d{6})\b", text)
    if campaign_match and not year_match:
        matched = next(
            (
                key
                for key, value in SNAPSHOTS.items()
                if any(
                    row["NHTSACampaignNumber"].lower() == campaign_match.group(1) for row in value["recalls"]
                )
            ),
            None,
        )
        if matched:
            key, year = matched.split(":")
            text += " " + year + " " + VEHICLES[key][1].lower()
            year_match = re.search(r"\b(20\d{2})\b", text)
    vehicle = next(
        (
            key
            for key, (_, model, brand) in VEHICLES.items()
            if re.search(r"\b" + re.escape(model.lower()) + r"\b", text)
            or (brand == "porsche" and "porsche" in text)
        ),
        None,
    )
    if context and not vehicle:
        vehicle = "porsche-911"
    if not vehicle or not year_match:
        return {
            "response": "Tell me the vehicle and model year, for example “2025 Porsche 911 recalls” or “2026 Atlas recalls”. I will show the affected system, safety consequence and manufacturer remedy here. A VIN check confirms whether your specific car is affected.",
            "intent": "service",
            "source": "nhtsa_recall_lookup",
            "links": [],
            "citations": [],
            "usage": {},
        }
    try:
        result = lookup(vehicle, int(year_match.group(1)))
    except ValueError:
        return {
            "response": "Choose a model year from 2019 to 2027.",
            "intent": "service",
            "source": "nhtsa_recall_lookup",
            "links": [],
            "citations": [],
            "usage": {},
        }
    if result["status"] == "unavailable":
        response = result["error"] + " Check your VIN on NHTSA or contact the dealership."
    else:
        response = f"{len(result['cards'])} NHTSA model-level campaigns for {result['year']} {result['make']} {result['model']}. Review the details below; campaign coverage is not a VIN-specific result."
        if result["status"] == "saved_snapshot":
            response += " Live lookup failed; showing the dated saved official response."
        if any(c["do_not_drive"] for c in result["cards"]):
            response += " A campaign includes a DO NOT DRIVE instruction for affected vehicles. Read the remedy and confirm your VIN immediately."
    store = LOCATIONS[VEHICLES[vehicle][2]]
    response += (
        "\n\n"
        + store["name"]
        + " service: "
        + store["departments"]["service"]["phone"]
        + ". No appointment has been reserved."
    )
    return {
        "response": response,
        "intent": "service",
        "source": "nhtsa_recall_lookup",
        "usage": {},
        "links": [
            {"label": "Check your VIN on NHTSA", "url": "https://www.nhtsa.gov/recalls", "kind": "recall"},
            {
                "label": store["name"] + " — request recall service",
                "url": store["links"]["service"],
                "kind": "service",
            },
        ],
        "citations": [],
        "recall_cards": result["cards"],
        "recall_status": result["status"],
        "brand": store["id"],
        "location_id": store["id"],
        "vin_verified": False,
    }

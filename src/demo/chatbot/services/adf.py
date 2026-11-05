"""ADF 1.0 (Auto-lead Data Format) XML, the lead format dealer CRMs (VinSolutions, DealerSocket,
Elead, etc.) ingest. Built with ElementTree so every value is XML-escaped; control characters
are stripped upstream (``text.clean_text``) because XML 1.0 cannot represent them.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ..text import clean_text

_INTEREST = {
    "buy": "buy",
    "lease": "lease",
    "trade-in": "trade-in",
    "service": "test-drive",
    "test_drive": "test-drive",
}


def _sub(parent: ET.Element, tag: str, text: Any = None, **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, tag, {k: v for k, v in attrs.items() if v is not None})
    if text not in (None, ""):
        element.text = clean_text(str(text), max_len=2000)
    return element


def build_adf(lead: dict[str, Any], *, vendor_name: str, provider_name: str = "Jack Ingram AI Assistant") -> str:
    root = ET.Element("adf")
    prospect = _sub(root, "prospect", status="new")
    _sub(prospect, "id", lead.get("id"), source=provider_name)
    _sub(prospect, "requestdate", lead.get("created_at"))
    vehicle = lead.get("vehicle") or {}
    vehicle_el = _sub(
        prospect,
        "vehicle",
        interest=_INTEREST.get(str(lead.get("interest")), "buy"),
        status=vehicle.get("condition") if vehicle.get("condition") in ("new", "used") else None,
    )
    for tag in ("year", "make", "model", "vin"):
        if vehicle.get(tag):
            _sub(vehicle_el, tag, vehicle[tag])
    if vehicle.get("stock_number"):
        _sub(vehicle_el, "stock", vehicle["stock_number"])
    customer = _sub(prospect, "customer")
    contact = _sub(customer, "contact")
    _sub(contact, "name", lead.get("first_name"), part="first")
    if lead.get("last_name"):
        _sub(contact, "name", lead["last_name"], part="last")
    if lead.get("email"):
        _sub(contact, "email", lead["email"])
    if lead.get("phone"):
        _sub(contact, "phone", lead["phone"], type="voice")
    comments = [c for c in (lead.get("comments"), lead.get("appointment_summary")) if c]
    if comments:
        _sub(customer, "comments", " | ".join(comments))
    vendor = _sub(prospect, "vendor")
    _sub(vendor, "vendorname", vendor_name)
    provider = _sub(prospect, "provider")
    _sub(provider, "name", provider_name, part="full")
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<?adf version="1.0"?>\n' + body + "\n"

"""Deterministic responder used when Claude is not configured or temporarily unavailable.

It answers from the same services the tools use (never invents facts), and its intent
classifier doubles as the analytics topic tagger, so topics are counted identically whether
or not the LLM answered.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from ..knowledge import BRAND_ALIASES
from ..resilience import UpstreamError
from ..services.finance import PaymentInput, TradeInInput, estimate_payment, estimate_trade_in
from ..services.inventory import SearchFilters
from ..vin import find_vin

if TYPE_CHECKING:
    from ..app_state import Services

_TOPICS: list[tuple[str, re.Pattern[str]]] = [
    ("human", re.compile(r"\b(human|real person|representative|live agent|salesperson|talk to (a|an|someone|somebody)|"
                         r"speak (to|with)|call me|someone call)\b")),
    ("recalls", re.compile(r"\brecalls?\b")),
    ("safety", re.compile(r"\b(safety ratings?|crash test|ncap|star ratings?)\b")),
    ("appointment", re.compile(r"\b(appointment|schedule|book|test[- ]drive|oil change|bring (it|my car|my vehicle) in)\b")),
    ("trade_in", re.compile(r"\b(trade[- ]?in|trading in|worth|value my|sell my)\b")),
    ("lease", re.compile(r"\blease\b")),
    ("finance", re.compile(r"\b(payments?|financ\w*|apr|interest rate|monthly|loan)\b")),
    ("specials", re.compile(r"\b(specials?|deals?|offers?|incentives?|rebates?|promotions?)\b")),
    ("compare", re.compile(r"\b(compare|versus|vs\.?|difference between)\b")),
    ("service_history", re.compile(r"\bservice (history|records)\b")),
    ("hours", re.compile(r"\b(hours|open|opening|close|closing)\b")),
    ("location", re.compile(r"\b(where|address|location|located|directions)\b")),
    ("contact", re.compile(r"\b(phone|number|contact|email)\b")),
    ("brands", re.compile(r"\b(brands?|makes? do you|what (cars|vehicles) do you)\b")),
    ("service", re.compile(r"\b(service|maintenance|repair|tires?|brakes?)\b")),
    ("inventory", re.compile(r"\b(inventory|in stock|available|have any|looking for|suvs?|sedans?|trucks?|coupes?|"
                             r"electric|ev|hybrid|under \$?\d|used|pre-owned|certified|cpo)\b")),
    ("greeting", re.compile(r"^\s*(hi|hello|hey|howdy|good (morning|afternoon|evening))\b")),
]  # fmt: skip
_BRAND_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(BRAND_ALIASES, key=len, reverse=True)) + r")\b")
_STOCK_RE = re.compile(r"\b[A-Z]{1,2}\d{2}-\d{4}\b", re.IGNORECASE)
_MONEY_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", re.IGNORECASE)
_MAX_PRICE_RE = re.compile(
    r"\b(?:under|below|less than|max(?:imum)?|budget(?: of| is)?|up to)\s*\$?\s*(\d[\d,]*)\s*(k)?\b"
)
_APR_RE = re.compile(r"(\d{1,2}(?:\.\d{1,3})?)\s*%")
_TERM_RE = re.compile(r"\b(\d{2})\s*(?:months?|mos?|mo)\b|\b(\d)\s*(?:years?|yrs?)\b")
_DOWN_RE = re.compile(r"\$?\s?(\d[\d,]*)\s*(k)?\s*down\b|\bdown(?: payment)?(?: of)?\s*\$?\s?(\d[\d,]*)\s*(k)?")
_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
_MILES_RE = re.compile(r"\b(\d[\d,]*)\s*(k)?\s*(?:miles|mi)\b|\b(\d{2,3})\s*k\b")
_BODY = {"suv": "SUV", "suvs": "SUV", "sedan": "Sedan", "sedans": "Sedan", "truck": "Truck", "trucks": "Truck",
         "coupe": "Coupe", "coupes": "Coupe", "wagon": "Wagon", "van": "Van"}  # fmt: skip


def classify(text: str) -> str:
    lower = text.lower()
    if find_vin(text) and not re.search(r"\b(recall|service history)\b", lower):
        return "vin"
    for topic, pattern in _TOPICS:
        if pattern.search(lower):
            return topic
    if _BRAND_RE.search(lower):
        return "inventory"
    return "other"


def brands_mentioned(text: str) -> list[str]:
    return sorted({BRAND_ALIASES[m.group(1)] for m in _BRAND_RE.finditer(text.lower())})


def _amount(raw: str | None, k: str | None) -> Decimal | None:
    if not raw:
        return None
    try:
        value = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    return value * 1000 if k else value


class FallbackResponder:
    def __init__(self, services: Services) -> None:
        self.s = services

    async def respond(self, text: str, conversation_id: str) -> tuple[str, dict[str, Any]]:
        topic = classify(text)
        handler = getattr(self, f"_{topic}", self._other)
        reply, meta = await handler(text, conversation_id)
        return reply, {"topic": topic, **meta}

    # --- facts ---------------------------------------------------------------------------
    def _verify_note(self) -> str:
        return "" if self.s.knowledge.verified else "\n(Please confirm by phone or on our website before visiting.)"

    async def _greeting(self, text: str, conv: str) -> tuple[str, dict]:
        return (
            f"Hi! I'm the virtual assistant for {self.s.knowledge.name}. I can search inventory, estimate payments and"
            " trade-in values, check recalls, book service or test drives, and connect you with our team."
            " What can I help you with?",
            {},
        )

    async def _hours(self, text: str, conv: str) -> tuple[str, dict]:
        kb = self.s.knowledge
        note = kb.data.get("hours_note") or ""
        return (
            f"Sales: {kb.hours_text('sales')}\nService: {kb.hours_text('service')}\n{note}{self._verify_note()}",
            {},
        )

    async def _location(self, text: str, conv: str) -> tuple[str, dict]:
        kb = self.s.knowledge
        lines = [f"{kb.name} — {kb.data['main_address']}"]
        for store in kb.data["stores"]:
            if store.get("address"):
                lines.append(f"• {store['name']}: {store['address']}")
        return "\n".join(lines) + self._verify_note(), {}

    async def _contact(self, text: str, conv: str) -> tuple[str, dict]:
        kb = self.s.knowledge
        wanted = brands_mentioned(text)
        lines = []
        for store in kb.data["stores"]:
            if wanted and store["brand"] not in wanted:
                continue
            phones = [f"sales {store['sales_phone']}" if store.get("sales_phone") else None,
                      f"service {store['service_phone']}" if store.get("service_phone") else None]  # fmt: skip
            phones = [p for p in phones if p]
            if phones:
                lines.append(f"• {store['name']}: " + ", ".join(phones))
        lines.append(f"Website: {kb.data['website']}")
        return "\n".join(lines) + self._verify_note(), {}

    async def _brands(self, text: str, conv: str) -> tuple[str, dict]:
        return "We represent " + ", ".join(self.s.knowledge.brands) + ". Which brand are you interested in?", {}

    async def _service(self, text: str, conv: str) -> tuple[str, dict]:
        kb = self.s.knowledge
        return (
            "Our service department offers "
            + ", ".join(kb.data["services"]["service"]).lower()
            + f".\nService hours: {kb.hours_text('service')}\nTap 'Book appointment' to schedule a visit.",
            {},
        )

    # --- inventory ---------------------------------------------------------------------------
    def _filters(self, text: str) -> SearchFilters:
        lower = text.lower()
        brand = brands_mentioned(text)
        models = {v.model.lower(): v.model for v in self.s.inventory.vehicles.values()}
        model = next((name for key, name in models.items() if re.search(r"\b" + re.escape(key) + r"\b", lower)), None)
        body = next((value for key, value in _BODY.items() if re.search(r"\b" + key + r"\b", lower)), None)
        fuel = "Electric" if re.search(r"\b(electric|ev)\b", lower) else ("Hybrid" if "hybrid" in lower else None)
        condition = None
        if re.search(r"\b(certified|cpo)\b", lower):
            condition = "cpo"
        elif re.search(r"\b(used|pre-owned|preowned)\b", lower):
            condition = "used"
        elif re.search(r"\b(brand[- ]new|new (?:car|vehicle|suv|sedan|truck|coupe))\b", lower):
            condition = "new"
        max_price = None
        match = _MAX_PRICE_RE.search(lower)
        if match:
            max_price = _amount(match.group(1), match.group(2))
        year = _YEAR_RE.search(lower)
        return SearchFilters(
            make=brand[0] if len(brand) == 1 else None,
            model=model,
            body_style=body,
            fuel_type=fuel,
            condition=condition,
            max_price=int(max_price) if max_price else None,
            min_year=int(year.group(1)) if year else None,
            max_year=int(year.group(1)) if year else None,
            sort="price_asc",
            limit=5,
        )

    async def _inventory(self, text: str, conv: str) -> tuple[str, dict]:
        result = self.s.inventory.search(self._filters(text))
        if not result["vehicles"]:
            return ("I couldn't find a match in current inventory. Try a different brand, body style or budget, or"
                    " tap 'Contact me' and our team will look for you.", {})  # fmt: skip
        lines = [f"I found {result['total']} match{'es' if result['total'] != 1 else ''}. Here are the best-priced:"]
        for v in result["vehicles"]:
            miles = f", {v['mileage']:,} mi" if v["condition"] != "new" else ""
            label = {"new": "New", "used": "Used", "cpo": "Certified"}[v["condition"]]
            lines.append(f"• {label} {v['year']} {v['make']} {v['model']} {v['trim'] or ''} — ${v['price']:,}{miles}"
                         f" (stock {v['stock_number']})".replace("  ", " "))  # fmt: skip
        if result.get("is_sample"):
            lines.append("Note: these are sample listings for demonstration, not live inventory.")
        return "\n".join(lines), {"is_sample": result.get("is_sample", False)}

    async def _compare(self, text: str, conv: str) -> tuple[str, dict]:
        stocks = [m.group(0).upper() for m in _STOCK_RE.finditer(text)]
        try:
            result = self.s.inventory.compare(stocks)
        except ValueError as exc:
            return f"{exc} You can find stock numbers in search results (for example 'N26-0101').", {}
        lines = ["Comparison:"]
        for v in result["vehicles"]:
            lines.append(f"• {v['stock_number']}: {v['year']} {v['make']} {v['model']} {v['trim'] or ''}, ${v['price']:,},"
                         f" {v['fuel_type']}, {v['drivetrain'] or ''}".rstrip(", "))  # fmt: skip
        if result["differences"]:
            lines.append("Key differences: " + ", ".join(sorted(result["differences"])[:8]))
        lines.append(f"Lowest price: {result['lowest_price']}.")
        return "\n".join(lines), {}

    async def _specials(self, text: str, conv: str) -> tuple[str, dict]:
        brand = brands_mentioned(text)
        result = self.s.inventory.current_offers(brand[0] if len(brand) == 1 else None)
        if not result["offers"]:
            return "I don't have current offers on file. Our sales team can share today's incentives.", {}
        lines = ["Current offers:"] + [
            f"• {o['brand']}: {o['title']} — {o['description']}" for o in result["offers"][:5]
        ]
        if result.get("is_sample"):
            lines.append("Note: these are sample offers for demonstration only.")
        return "\n".join(lines), {}

    # --- money ---------------------------------------------------------------------------------
    async def _finance(self, text: str, conv: str) -> tuple[str, dict]:
        lower = text.lower()
        down_match = _DOWN_RE.search(lower)
        down = None
        if down_match:
            down = _amount(down_match.group(1) or down_match.group(3), down_match.group(2) or down_match.group(4))
        amounts = [_amount(m.group(1), m.group(2)) for m in _MONEY_RE.finditer(lower)]
        price = next((a for a in amounts if a and a != down and a >= 1000), None)
        apr = _APR_RE.search(lower)
        term = _TERM_RE.search(lower)
        months = int(term.group(1)) if term and term.group(1) else (int(term.group(2)) * 12 if term else None)
        if not (price and apr and months):
            return ("I can estimate a monthly payment. Tell me the price, APR and term, for example:"
                    " \"payment on $35,000 at 6.9% for 60 months with $3,000 down\".", {})  # fmt: skip
        try:
            est = estimate_payment(PaymentInput(price=price, apr_percent=Decimal(apr.group(1)), term_months=months,
                                                down_payment=down or Decimal(0)))  # fmt: skip
        except ValueError as exc:
            return f"I couldn't compute that: {exc}", {}
        monthly = Decimal(est["monthly_payment"])
        financed = Decimal(est["amount_financed"])
        return (f"Estimated payment: ${monthly:,.2f}/mo for {months} months at {apr.group(1)}% APR on"
                f" ${financed:,.2f} financed.\n{est['disclaimer']}", {})  # fmt: skip

    async def _lease(self, text: str, conv: str) -> tuple[str, dict]:
        return ("Lease payments depend on MSRP, the lender's residual value and money factor. Share the MSRP and"
                " term and our finance team can quote current lease programs, or tap 'Contact me'.", {})  # fmt: skip

    async def _trade_in(self, text: str, conv: str) -> tuple[str, dict]:
        lower = text.lower()
        year = _YEAR_RE.search(lower)
        brand = brands_mentioned(text)
        make = brand[0] if brand else None
        if make is None:
            other = re.search(
                r"\b(toyota|honda|ford|chevrolet|chevy|gmc|ram|jeep|hyundai|kia|subaru|mazda|bmw|lexus|tesla)\b", lower
            )
            make = {"chevy": "chevrolet"}.get(other.group(1), other.group(1)) if other else None
        miles_match = _MILES_RE.search(lower)
        miles = None
        if miles_match:
            if miles_match.group(3):
                miles = int(miles_match.group(3)) * 1000
            else:
                miles = int(_amount(miles_match.group(1), miles_match.group(2)) or 0)
        condition = next((c for c in ("excellent", "good", "fair", "poor") if c in lower), "good")
        if not (year and make and miles is not None):
            return ("I can give a rough trade-in range. Tell me the year, make, model, mileage and condition, for"
                    " example: \"2019 Honda Accord, 62,000 miles, good condition\".", {})  # fmt: skip
        try:
            est = estimate_trade_in(
                TradeInInput(year=int(year.group(1)), make=make, mileage=miles, condition=condition)
            )
        except ValueError as exc:
            return f"I couldn't estimate that: {exc}", {}
        return (f"Rough trade-in range: ${int(est['estimated_low']):,} – ${int(est['estimated_high']):,}.\n"
                f"{est['disclaimer']}", {})  # fmt: skip

    # --- vehicle data ---------------------------------------------------------------------------
    async def _vin(self, text: str, conv: str) -> tuple[str, dict]:
        vin = find_vin(text)
        try:
            decoded = await self.s.nhtsa.decode_vin(vin or "")
        except ValueError as exc:
            return f"That VIN doesn't look right: {exc}", {}
        except UpstreamError:
            return "I couldn't reach the NHTSA VIN service right now. Please try again shortly.", {}
        if not decoded["decoded"]:
            return f"NHTSA couldn't decode that VIN. {decoded.get('nhtsa_message') or ''}".strip(), {}
        reply = (f"That VIN is a {decoded['year']} {decoded['make']} {decoded['model']}"
                 f"{' ' + decoded['trim'] if decoded.get('trim') else ''}"
                 f"{', ' + decoded['body_class'] if decoded.get('body_class') else ''}.")  # fmt: skip
        try:
            recalls = await self.s.nhtsa.recalls(decoded["make"], decoded["model"], int(decoded["year"]))
            if recalls["count"]:
                reply += (
                    f" NHTSA lists {recalls['count']} recall(s) for this make/model/year; our service team can"
                    " confirm whether this vehicle still needs any remedy."
                )
            else:
                reply += " NHTSA lists no recalls for this make/model/year."
        except (UpstreamError, ValueError):
            pass
        return reply, {}

    def _ymm(self, text: str) -> tuple[int, str, str] | None:
        lower = text.lower()
        year = _YEAR_RE.search(lower)
        brand = brands_mentioned(text)
        if not (year and brand):
            return None
        models = {v.model.lower(): v.model for v in self.s.inventory.vehicles.values() if v.make == brand[0]}
        model = next((name for key, name in models.items() if key in lower), None)
        if model is None:
            after = re.search(re.escape(brand[0].lower().split("-")[0]) + r"\w*[\s-]+([a-z0-9.\-]+)", lower)
            model = after.group(1) if after else None
        return (int(year.group(1)), brand[0], model) if model else None

    async def _recalls(self, text: str, conv: str) -> tuple[str, dict]:
        if find_vin(text):
            return await self._vin(text, conv)
        ymm = self._ymm(text)
        if not ymm:
            return "Tell me the year, make and model (or the VIN) and I'll check NHTSA recalls.", {}
        year, make, model = ymm
        try:
            result = await self.s.nhtsa.recalls(make, model, year)
        except (UpstreamError, ValueError):
            return "I couldn't reach the NHTSA recall service right now. You can also check nhtsa.gov/recalls.", {}
        if not result["count"]:
            return f"NHTSA lists no recalls for the {year} {make} {model}.", {}
        lines = [f"NHTSA lists {result['count']} recall(s) for the {year} {make} {model}:"]
        lines += [f"• {r['campaign']}: {r['component']}" for r in result["recalls"][:5]]
        lines.append(result["note"])
        return "\n".join(lines), {}

    async def _safety(self, text: str, conv: str) -> tuple[str, dict]:
        ymm = self._ymm(text)
        if not ymm:
            return "Tell me the year, make and model and I'll look up NHTSA crash-test ratings.", {}
        year, make, model = ymm
        try:
            result = await self.s.nhtsa.safety_ratings(make, model, year)
        except (UpstreamError, ValueError):
            return "I couldn't reach the NHTSA ratings service right now.", {}
        if not result["vehicles"]:
            return f"NHTSA has no crash-test ratings on file for the {year} {make} {model}.", {}
        lines = [f"NHTSA ratings for the {year} {make} {model}:"]
        lines += [f"• {v['description']}: overall {v['overall'] or 'not rated'} stars" for v in result["vehicles"]]
        return "\n".join(lines), {}

    async def _service_history(self, text: str, conv: str) -> tuple[str, dict]:
        return "I can look up service records with the VIN and the owner's last name. Please share both.", {}

    # --- actions --------------------------------------------------------------------------------
    async def _appointment(self, text: str, conv: str) -> tuple[str, dict]:
        dept = "test_drive" if re.search(r"test[- ]drive", text.lower()) else "service"
        availability = await self.s.appointments.availability(dept, None, 3)
        slots = availability["slots"][:6]
        if not slots:
            return "I don't see open times in the next few days. Tap 'Contact me' and the team will find a time.", {}
        lines = [f"Next open {availability['label'].lower()} times:"] + [f"• {s['label']}" for s in slots]
        lines.append("Tap 'Book appointment' to reserve one.")
        return "\n".join(lines), {"suggest": "book"}

    async def _human(self, text: str, conv: str) -> tuple[str, dict]:
        result = await self.s.db.run(self.s.handoffs.request_sync, conv, "customer asked for a person")
        if result["created"]:
            await self.s.analytics.record("handoff.requested", conv, within_hours=result["within_hours"])
        if result["within_hours"]:
            reply = "I've asked a member of our team to join this chat. Please stay here; they'll reply shortly."
        else:
            when = result.get("next_opening") or "when we next open"
            reply = (f"Our team is away right now; I've passed your request along and they'll pick it up {when}."
                     " Tap 'Contact me' to leave your number for a call back.")  # fmt: skip
        return reply, {"handoff": result}

    async def _other(self, text: str, conv: str) -> tuple[str, dict]:
        return (
            "I can help with vehicle searches, payment and trade-in estimates, recalls, service and test-drive"
            " appointments, or connecting you with our team. What would you like to do?",
            {},
        )

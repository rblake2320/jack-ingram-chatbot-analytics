"""Reviewed official facts. A scrape can propose changes; it cannot publish them."""

import json
import re
from datetime import date
from pathlib import Path

CATALOG = json.loads((Path(__file__).parent / "data" / "dealerships.json").read_text(encoding="utf-8"))
GROUP = {**CATALOG["group"], "locations": CATALOG["locations"], "reviewed_at": CATALOG["reviewed_at"]}
LOCATIONS = {row["id"]: row for row in CATALOG["locations"]}
ALIASES = {
    "audi": r"\baudi\b",
    "mercedes": r"\b(mercedes(?:-benz)?|benz)\b",
    "nissan": r"\bnissan\b",
    "porsche": r"\bporsche\b",
    "volkswagen": r"\b(volkswagen|vw)\b",
    "volvo": r"\bvolvo\b",
    "signature": r"\b(signature|used cars|pre-owned)\b",
    "body-shop": r"\b(body ?shop|collision|bodywork)\b",
}


class KnowledgeBase:
    DEALERSHIP_INFO = GROUP

    def select(self, message, history=(), location_id=None):
        lowered = message.lower()
        found = [LOCATIONS[key] for key, pattern in ALIASES.items() if re.search(pattern, lowered)]
        if any(row["id"] == "body-shop" for row in found):
            return [LOCATIONS["body-shop"]]
        if any(term in lowered for term in ("all locations", "all your locations", "all dealerships")):
            return list(LOCATIONS.values())
        if found:
            return found
        if location_id in LOCATIONS:
            return [LOCATIONS[location_id]]
        for turn in reversed(history):
            if turn.get("role") == "user":
                found = self.select(turn.get("content", ""), (), None)
                if found:
                    return found
        return []

    def get_brand_models(self, brand):
        return LOCATIONS.get(brand, {}).get("models", [])

    def fresh(self):
        return (date.today() - date.fromisoformat(CATALOG["reviewed_at"])).days <= 30

    def format_hours(self, department, location):
        if not self.fresh():
            return "Hours need a refresh. Please check the official contact page or call before visiting."
        data = location["departments"].get(department)
        if not data:
            return f"{department.title()} hours are not published in this directory. Please call."
        hours = data["hours"]
        lines = [f"{department.replace('-', ' ').title()} hours (Central Time):"]
        weekdays = [
            hours.get(day, "Not published; call")
            for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
        ]
        if len(set(weekdays)) == 1:
            lines.append("Monday–Friday: " + weekdays[0])
        else:
            lines.extend(
                f"{day}: {value}"
                for day, value in zip(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"), weekdays)
            )
        lines.extend(f"{day}: {hours.get(day, 'Not published; call')}" for day in ("Saturday", "Sunday"))
        return "\n".join(lines)

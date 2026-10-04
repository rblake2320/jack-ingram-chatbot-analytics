"""Answers grounded in the reviewed official directory; paid generation is optional."""

import re

from .api_gateway import APIGateway
from .knowledge_base import CATALOG, GROUP, KnowledgeBase
from .routing import baseline


class APIRouter:
    def __init__(self, provider=None, laya=None):
        self.provider, self.laya = provider, laya
        self.gateway, self.knowledge = APIGateway(), KnowledgeBase()

    def extract_vehicle_params(self, message):
        makes = ("nissan", "audi", "mercedes", "porsche", "volkswagen", "volvo")
        lowered = message.lower()
        make = next((make for make in makes if re.search(r"\b" + make + r"\b", lowered)), None)
        model = None
        for candidate_make in [make] if make else makes:
            for candidate_model in self.knowledge.get_brand_models(candidate_make):
                if re.search(r"\b" + re.escape(candidate_model.lower()) + r"\b", lowered):
                    make, model = candidate_make, candidate_model
                    break
            if model:
                break
        style = next((s for s in ("suv", "sedan", "truck") if re.search(r"\b" + s + r"s?\b", lowered)), None)
        return {"make": make, "model": model, "body_style": style}

    def process_request(self, message, history, location_id=None):
        intent = baseline(message)
        query = self.extract_vehicle_params(message)
        lowered = message.lower()
        locations = self.knowledge.select(message, history, location_id)
        if not locations and query["make"]:
            locations = self.knowledge.select(query["make"])
        if intent == "other" and query["make"]:
            intent = "inventory"
        department = "parts" if "parts" in lowered else "service" if "service" in lowered else "sales"
        if locations and locations[0]["id"] == "body-shop":
            department = "body-shop"
        result = {
            "intent": intent,
            "brand": query["make"] or (locations[0]["id"] if len(locations) == 1 else "all"),
            "source": "official_website",
            "usage": {},
            "data_status": "official_snapshot",
            "links": [],
            "citations": [],
            "reviewed_at": CATALOG["reviewed_at"],
            "location_id": locations[0]["id"] if len(locations) == 1 else None,
        }

        def link(label, url, kind):
            result["links"].append({"label": label, "url": url, "kind": kind})

        if "finance" in lowered or "financing" in lowered or "credit" in lowered:
            text = "The finance team can explain applications and available options. Approval, rates and payments require a lender decision. Please use the official secure application; avoid sharing financial or identity details here."
            link(
                "Official finance application",
                locations[0]["links"].get("finance", GROUP["finance_url"])
                if len(locations) == 1
                else GROUP["finance_url"],
                "finance",
            )
        elif "trade" in lowered or "sell my" in lowered:
            text = "Use the official trade-in tool for an appraisal. The dealership will confirm the final value after reviewing your vehicle."
            link(
                "Value your trade",
                locations[0]["links"].get("trade", GROUP["trade_url"])
                if len(locations) == 1
                else GROUP["trade_url"],
                "trade",
            )
        elif intent == "hours":
            if not locations:
                text = "Which location and department would you like? Select a store above, or ask “Nissan service hours”. Sales, service and parts hours differ."
            else:
                text = "\n\n".join(
                    row["name"]
                    + "\n"
                    + self.knowledge.format_hours(department, row)
                    + ("\n" + "\n".join(row["notes"]) if row["notes"] else "")
                    for row in locations
                )
                text += "\n\nPublished weekly hours; call to confirm holiday changes."
        elif intent == "contact":
            locations = locations or CATALOG["locations"]
            text = "\n\n".join(
                f"{row['name']}\n{row['address']}\n{department.title()}: {row['departments'].get(department, {}).get('phone') or row['phone']}"
                for row in locations
            )
        elif intent in ("service", "appointment"):
            if not locations:
                text = "Which location should help? Select your brand for service or a test drive, or choose Body Shop for collision repair."
            else:
                text = "\n\n".join(
                    row["name"]
                    + "\n"
                    + (
                        "Collision repairs and estimates"
                        if row["id"] == "body-shop"
                        else "Parts enquiries"
                        if department == "parts"
                        else "Service scheduling"
                        if intent == "service" or "service" in lowered
                        else "Test-drive enquiries"
                    )
                    + ": use the official page below or call "
                    + (
                        row["departments"]
                        .get("service" if intent == "service" else department, {})
                        .get("phone")
                        or row["phone"]
                    )
                    + "."
                    for row in locations
                )
                for row in locations:
                    action = (
                        "parts"
                        if department == "parts"
                        else "service"
                        if intent == "service" or "service" in lowered or row["id"] == "body-shop"
                        else "contact"
                    )
                    link(
                        row["name"] + (" — schedule service" if action == "service" else " — contact"),
                        row["links"].get(action, row["links"]["contact"]),
                        action,
                    )
                text += "\nNo appointment has been reserved. Complete your request on the dealership's official page."
        elif intent == "inventory":
            if re.search(r"\b(sample|demonstration)\b", lowered):
                data = self.gateway.get_vehicle_data(query)
                text = "Demonstration inventory — sample 2024 vehicles, not live stock or current prices.\n"
                text += (
                    "\n".join(
                        f"{car['year']} {car['make']} {car['model']} {car['trim']} — sample price ${car['price']:,.0f}"
                        for car in data["inventory"]
                    )
                    or "No matching sample vehicles."
                )
                result["source"], result["data_status"] = "demo_inventory", "demo_not_live"
            else:
                text = "Browse the dealership's current inventory using the official links below. Stock and prices change; the dealership will confirm availability."
            for row in locations:
                if row["id"] != "body-shop":
                    link(row["name"] + " — inventory", row["links"]["inventory"], "inventory")
            if not result["links"]:
                link("Browse all Jack Ingram inventory", GROUP["inventory_url"], "inventory")
        elif self.provider:
            context = {"group": GROUP, "selected_locations": locations, "reviewed_at": CATALOG["reviewed_at"]}
            result.update(self.provider.send_message(message, history, context))
            text = result["response"]
        else:
            text = "Welcome to Jack Ingram Motors. I can help with eight locations, sales and service hours, current inventory links, financing, trade-ins and dealership contacts. Select a store or ask “Where is Porsche?”"
            result["source"] = "local"
        for row in locations:
            link(row["name"] + " — location & contact", row["links"]["contact"], "contact")
            result["citations"].append(
                {"label": row["name"], "url": row["sources"][0]["url"], "reviewed_at": CATALOG["reviewed_at"]}
            )
        if result["source"] == "official_website" and not result["citations"]:
            result["citations"] = [
                {"label": GROUP["name"], "url": GROUP["website"], "reviewed_at": CATALOG["reviewed_at"]}
            ]
        result["response"] = text.strip()
        result["facts_fresh"] = self.knowledge.fresh()
        if self.laya:
            result["routing_advice"] = self.laya.classify(message)
        return result

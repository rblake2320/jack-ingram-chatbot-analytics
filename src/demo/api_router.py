"""Deterministic useful demo responses; generation is an explicit opt-in."""

import re

from .api_gateway import APIGateway
from .config import DEALERSHIP_INFO
from .knowledge_base import KnowledgeBase
from .routing import baseline


class APIRouter:
    def __init__(self, provider=None, laya=None):
        self.provider = provider
        self.laya = laya
        self.gateway = APIGateway()
        self.knowledge = KnowledgeBase()

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
        body_style = next(
            (style for style in ("suv", "sedan", "truck") if re.search(r"\b" + style + r"s?\b", lowered)),
            None,
        )
        return {"make": make, "model": model, "body_style": body_style}

    def process_request(self, message, history):
        intent = baseline(message)
        query = self.extract_vehicle_params(message)
        if intent == "other" and query["make"]:
            intent = "inventory"
        result = {
            "intent": intent,
            "brand": query["make"] or "all",
            "source": "repository_reference",
            "usage": {},
            "data_status": "demo_not_live",
        }
        if intent == "hours":
            text = self.knowledge.format_hours("sales") + "\n" + self.knowledge.format_hours("service")
            text += "\nThese are repository reference hours. Please confirm before visiting."
        elif intent == "contact":
            text = f"Contact Jack Ingram Motors at {DEALERSHIP_INFO['phone']}.\n"
            text += f"Reference address: {DEALERSHIP_INFO['main_address']}.\n"
            text += DEALERSHIP_INFO["website"]
        elif intent == "appointment":
            text = (
                "To arrange a test drive or service appointment, call "
                + DEALERSHIP_INFO["phone"]
                + " or visit "
                + DEALERSHIP_INFO["website"]
                + "\nThis demo has no booking connection; no appointment has been reserved."
            )
            result["source"] = "handoff"
        elif intent == "inventory":
            data = self.gateway.get_vehicle_data(query)
            text = "Demonstration inventory — sample 2024 vehicles, not live stock or current prices.\n"
            if data["inventory"]:
                text += "\n".join(
                    f"{car['year']} {car['make']} {car['model']} {car['trim']} — "
                    f"sample price ${car['price']:,.0f}"
                    for car in data["inventory"]
                )
            else:
                text += "No matching sample vehicles."
            text += "\nFor current availability and offers, contact " + DEALERSHIP_INFO["phone"] + "."
            result["source"] = "demo_inventory"
        elif intent == "service":
            services = self.knowledge.DEALERSHIP_INFO["services"]["service"]
            text = "Repository service reference:\n" + "\n".join("- " + item for item in services)
            text += "\nConfirm services and availability at " + DEALERSHIP_INFO["phone"] + "."
        elif self.provider:
            context = {"dealership": DEALERSHIP_INFO, "inventory": self.gateway.get_vehicle_data(query)}
            result.update(self.provider.send_message(message, history, context))
            text = result["response"]
        else:
            text = (
                "Welcome! I can help you explore six brands, view sample vehicles, check reference hours, "
                "or contact the dealership. Try “Audi inventory”, “Service hours”, or “Book a test drive”. "
                "Open-ended AI answers require an explicitly configured provider."
            )
            result["source"] = "local"
        result["response"] = text.strip()
        if self.laya:
            result["routing_advice"] = self.laya.classify(message)
        return result

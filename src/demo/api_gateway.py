"""Explicitly labeled demonstration data. No invented API endpoints."""

from .inventory_db import InventoryDB


class APIGateway:
    def __init__(self):
        self.inventory = InventoryDB()

    def get_vehicle_data(self, query):
        return {
            "status": "demo",
            "inventory": self.inventory.get_inventory(
                query.get("make"), query.get("model"), query.get("body_style")
            ),
            "offers": self.inventory.get_offers(query.get("make"), query.get("model")),
            "notice": "Sample 2024 vehicles, not current dealership availability or pricing.",
        }

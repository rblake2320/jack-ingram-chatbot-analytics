"""
Simple in-memory inventory database for demo purposes
"""

from typing import Dict, Any, List
from datetime import datetime

class InventoryDB:
    """Simple in-memory inventory database"""
    
    def __init__(self):
        # Initialize with some sample inventory
        self.inventory = {
            "nissan": [
                {
                    "id": "N1",
                    "make": "Nissan",
                    "model": "Altima",
                    "year": 2024,
                    "trim": "SR",
                    "price": 26890,
                    "stock": "NA24001",
                    "color": "Pearl White",
                    "status": "available"
                },
                {
                    "id": "N2", 
                    "make": "Nissan",
                    "model": "Rogue",
                    "year": 2024,
                    "trim": "SV",
                    "price": 29990,
                    "stock": "NR24005",
                    "color": "Brilliant Silver",
                    "status": "available"
                }
            ],
            "audi": [
                {
                    "id": "A1",
                    "make": "Audi",
                    "model": "Q5",
                    "year": 2024,
                    "trim": "Premium Plus",
                    "price": 49800,
                    "stock": "AQ24003",
                    "color": "Mythos Black",
                    "status": "available"
                }
            ],
            "mercedes": [
                {
                    "id": "M1",
                    "make": "Mercedes-Benz",
                    "model": "GLE",
                    "year": 2024,
                    "trim": "450 4MATIC",
                    "price": 67800,
                    "stock": "MB24002",
                    "color": "Selenite Grey",
                    "status": "available"
                }
            ]
        }
        
        # Initialize special offers
        self.offers = {
            "nissan": [
                {
                    "id": "NO1",
                    "title": "2024 Altima Special",
                    "description": "$2000 Customer Cash + 1.9% APR for 60 months",
                    "expires": "2024-07-05",
                    "models": ["Altima"]
                },
                {
                    "id": "NO2",
                    "title": "Rogue Summer Event",
                    "description": "Lease for $299/mo for 36 months, $3999 down",
                    "expires": "2024-06-30",
                    "models": ["Rogue"]
                }
            ],
            "audi": [
                {
                    "id": "AO1",
                    "title": "Q5 Special Offer",
                    "description": "0.9% APR for 48 months",
                    "expires": "2024-06-30",
                    "models": ["Q5"]
                }
            ],
            "mercedes": [
                {
                    "id": "MO1",
                    "title": "Summer Event",
                    "description": "Special lease and finance offers on select models",
                    "expires": "2024-07-05",
                    "models": ["GLE", "GLC", "C-Class"]
                }
            ]
        }
        
    def get_inventory(self, make: str = None, model: str = None) -> List[Dict[str, Any]]:
        """Get filtered inventory"""
        if not make:
            # Return all inventory
            return [car for brand in self.inventory.values() for car in brand]
            
        inventory = self.inventory.get(make.lower(), [])
        
        if model:
            inventory = [car for car in inventory if car["model"].lower() == model.lower()]
            
        return inventory
        
    def get_offers(self, make: str = None, model: str = None) -> List[Dict[str, Any]]:
        """Get filtered special offers"""
        if not make:
            # Return all offers
            return [offer for brand in self.offers.values() for offer in brand]
            
        offers = self.offers.get(make.lower(), [])
        
        if model:
            offers = [
                offer for offer in offers 
                if not offer["models"] or model in offer["models"]
            ]
            
        # Filter expired offers
        today = datetime.now().date()
        return [
            offer for offer in offers
            if datetime.strptime(offer["expires"], "%Y-%m-%d").date() >= today
        ]
        
    def get_inventory_count(self, make: str = None) -> Dict[str, int]:
        """Get inventory counts by make"""
        if make:
            return {make: len(self.inventory.get(make.lower(), []))}
            
        return {
            brand: len(inventory)
            for brand, inventory in self.inventory.items()
        }
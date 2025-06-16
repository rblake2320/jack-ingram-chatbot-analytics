"""
# mypy: ignore-errors
Knowledge base for Jack Ingram Motors information
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta


class KnowledgeBase:
    """Manages dealership information and caches responses"""

    # Core dealership information
    DEALERSHIP_INFO = {
        "main": {
            "name": "Jack Ingram Motors",
            "location": "1000 Eastern Blvd, Montgomery, AL 36117",
            "phone": "(334) 277-5700",
            "website": "https://www.jackingram.com/",
            "about": """Jack Ingram Motors is Montgomery's premier automotive dealership, 
                    serving Central Alabama since 1959. We represent six luxury and mainstream 
                    brands, providing exceptional sales and service experiences.""",
        },
        "hours": {
            "sales": {
                "weekday": "9:00 AM - 7:00 PM",
                "saturday": "9:00 AM - 6:00 PM",
                "sunday": "Closed",
            },
            "service": {
                "weekday": "7:30 AM - 6:00 PM",
                "saturday": "8:00 AM - 5:00 PM",
                "sunday": "Closed",
            },
        },
        "brands": {
            "audi": {
                "name": "Audi Montgomery",
                "specialties": ["German luxury vehicles", "Performance cars", "SUVs"],
                "popular_models": ["A4", "Q5", "Q7", "e-tron"],
                "location": "Dedicated Audi showroom on Eastern Blvd",
                "tone": "sophisticated, tech-forward, premium",
            },
            "mercedes": {
                "name": "Mercedes-Benz of Montgomery",
                "specialties": ["Luxury vehicles", "Executive cars", "AMG performance"],
                "popular_models": ["C-Class", "E-Class", "GLE", "S-Class"],
                "location": "Exclusive Mercedes-Benz facility",
                "tone": "luxurious, prestigious, refined",
            },
            "nissan": {
                "name": "Jack Ingram Nissan",
                "specialties": ["Family vehicles", "Sedans", "SUVs", "Trucks"],
                "popular_models": ["Altima", "Rogue", "Titan", "Frontier"],
                "location": "Main dealership campus",
                "tone": "practical, reliable, value-focused",
            },
            "porsche": {
                "name": "Porsche of Montgomery",
                "specialties": ["Sports cars", "Performance SUVs", "Luxury vehicles"],
                "popular_models": ["911", "Cayenne", "Macan", "Taycan"],
                "location": "Dedicated Porsche showroom",
                "tone": "performance-oriented, exclusive, passionate",
            },
            "volkswagen": {
                "name": "Jack Ingram Volkswagen",
                "specialties": ["German engineering", "Family cars", "SUVs"],
                "popular_models": ["Jetta", "Tiguan", "Atlas", "ID.4"],
                "location": "Main dealership campus",
                "tone": "practical, engineered, accessible",
            },
            "volvo": {
                "name": "Jack Ingram Volvo",
                "specialties": ["Safety technology", "Luxury SUVs", "Wagons"],
                "popular_models": ["XC90", "XC60", "S60", "V60"],
                "location": "Main dealership campus",
                "tone": "safety-focused, scandinavian, sustainable",
            },
        },
        "services": {
            "sales": [
                "New vehicle sales",
                "Pre-owned vehicle sales",
                "Certified Pre-owned programs",
                "Fleet sales",
                "Vehicle customization",
                "Trade-in appraisals",
                "Financing options",
            ],
            "service": [
                "Factory authorized service",
                "Express service",
                "Collision repair",
                "Parts department",
                "Tire center",
                "Detailing services",
                "Loaner vehicles",
            ],
            "specials": [
                "New vehicle specials",
                "Service specials",
                "Parts specials",
                "Seasonal promotions",
                "Military discounts",
                "College graduate programs",
            ],
        },
    }

    def __init__(self):
        """Initialize knowledge base and response cache"""
        self.response_cache = {}
        self.cache_duration = timedelta(hours=24)  # Cache responses for 24 hours

    def get_dealership_info(
        self, category: Optional[str] = None, brand: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get dealership information by category and/or brand"""
        if not category and not brand:
            return self.DEALERSHIP_INFO

        if category and brand:
            if category in self.DEALERSHIP_INFO and brand in self.DEALERSHIP_INFO.get(
                "brands", {}
            ):
                return {
                    "brand_info": self.DEALERSHIP_INFO["brands"][brand],
                    category: self.DEALERSHIP_INFO.get(category, {}),
                }
        elif category:
            return {category: self.DEALERSHIP_INFO.get(category, {})}
        else:
            return {"brand_info": self.DEALERSHIP_INFO.get("brands", {}).get(brand, {})}

    def get_cached_response(self, query: str) -> Optional[str]:
        """Get cached response if available and not expired"""
        if query in self.response_cache:
            timestamp, response = self.response_cache[query]
            if datetime.now() - timestamp < self.cache_duration:
                return response
            else:
                del self.response_cache[query]
        return None

    def cache_response(self, query: str, response: str) -> None:
        """Cache a response with current timestamp"""
        self.response_cache[query] = (datetime.now(), response)

    def get_brand_tone(self, brand: str) -> str:
        """Get brand-specific tone for responses"""
        brand_info = self.DEALERSHIP_INFO.get("brands", {}).get(brand.lower(), {})
        return brand_info.get("tone", "professional and helpful")

    def format_hours(self, department: str) -> str:
        """Format hours for a specific department"""
        hours = self.DEALERSHIP_INFO.get("hours", {}).get(department, {})
        if not hours:
            return "Please call for hours"

        return f"""
{department.title()} Hours:
Monday-Friday: {hours.get('weekday', 'Call for hours')}
Saturday: {hours.get('saturday', 'Call for hours')}
Sunday: {hours.get('sunday', 'Closed')}
"""

    def get_brand_models(self, brand: str) -> list:
        """Get popular models for a specific brand"""
        brand_info = self.DEALERSHIP_INFO.get("brands", {}).get(brand.lower(), {})
        return brand_info.get("popular_models", [])

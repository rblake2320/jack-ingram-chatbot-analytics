"""
API Gateway to manage multiple data sources
"""

import aiohttp
import logging
from typing import Dict, Any, List
from datetime import datetime

class APIGateway:
    """Gateway for managing multiple API endpoints"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.base_urls = {
            "inventory": "http://localhost:5001",  # Inventory DB API
            "car": "https://car-api.example.com",  # CarAPI
            "nhtsa": "https://api.nhtsa.gov"       # NHTSA API
        }
        
    async def get_vehicle_data(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get comprehensive vehicle data from all sources
        
        Args:
            query: Search parameters like make, model, year
            
        Returns:
            Combined data from all sources
        """
        results = {}
        
        async with aiohttp.ClientSession() as session:
            # Get data concurrently from all sources
            tasks = [
                self.get_inventory_data(session, query),
                self.get_car_specs(session, query),
                self.get_safety_ratings(session, query)
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Combine results
            results["inventory"] = responses[0] if not isinstance(responses[0], Exception) else {}
            results["specs"] = responses[1] if not isinstance(responses[1], Exception) else {}
            results["safety"] = responses[2] if not isinstance(responses[2], Exception) else {}
            
        return results
        
    async def get_inventory_data(
        self, 
        session: aiohttp.ClientSession,
        query: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get current inventory data"""
        try:
            async with session.get(
                f"{self.base_urls['inventory']}/vehicles",
                params=query
            ) as response:
                return await response.json()
        except Exception as e:
            self.logger.error(f"Inventory API error: {str(e)}")
            return {}
            
    async def get_car_specs(
        self,
        session: aiohttp.ClientSession,
        query: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get vehicle specifications"""
        try:
            async with session.get(
                f"{self.base_urls['car']}/specs",
                params=query
            ) as response:
                return await response.json()
        except Exception as e:
            self.logger.error(f"CarAPI error: {str(e)}")
            return {}
            
    async def get_safety_ratings(
        self,
        session: aiohttp.ClientSession,
        query: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get NHTSA safety ratings"""
        try:
            make = query.get("make", "")
            model = query.get("model", "")
            year = query.get("year", datetime.now().year)
            
            async with session.get(
                f"{self.base_urls['nhtsa']}/api/SafetyRatings",
                params={
                    "make": make,
                    "model": model,
                    "modelYear": year,
                    "format": "json"
                }
            ) as response:
                return await response.json()
        except Exception as e:
            self.logger.error(f"NHTSA API error: {str(e)}")
            return {}
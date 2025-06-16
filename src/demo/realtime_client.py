"""
# mypy: ignore-errors
Real-time data client combining multiple LLMs and data sources
"""

import aiohttp
import logging
from datetime import datetime
import pytz
from typing import Dict, Any


class RealtimeClient:
    """Client for fetching real-time information"""

    def __init__(
        self,
        perplexity_key: str = "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",
    ):
        self.perplexity_key = perplexity_key
        self.logger = logging.getLogger(__name__)

    async def get_realtime_info(self, query: str) -> Dict[str, Any]:
        """
        Get real-time information using multiple sources

        Args:
            query: User's query

        Returns:
            Dict containing real-time information
        """
        try:
            current_time = datetime.now(pytz.timezone("America/Chicago"))

            # Get real-time data from Perplexity
            perplexity_data = await self._get_perplexity_data(query, current_time)

            # Get web data
            web_data = await self._get_web_data(query)

            # Combine all real-time info
            return {
                "current_time": current_time.strftime("%B %d, %Y %H:%M:%S %Z"),
                "perplexity": perplexity_data,
                "web": web_data,
            }

        except Exception as e:
            self.logger.error(f"Error getting real-time info: {str(e)}")
            return {
                "error": str(e),
                "current_time": current_time.strftime("%B %d, %Y %H:%M:%S %Z"),
            }

    async def _get_perplexity_data(
        self, query: str, current_time: datetime
    ) -> Dict[str, Any]:
        """Get real-time data from Perplexity API"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "accept": "application/json",
                    "content-type": "application/json",
                    "authorization": f"Bearer {self.perplexity_key}",
                }

                # Add time context to query
                enhanced_query = f"""Current time: {current_time.strftime('%B %d, %Y %H:%M:%S %Z')}
                Question about Jack Ingram Motors in Montgomery, AL: {query}"""

                payload = {
                    "model": "sonar-medium-online",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a real-time information assistant for Jack Ingram Motors. Always include current date/time in responses.",
                        },
                        {"role": "user", "content": enhanced_query},
                    ],
                }

                async with session.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    return await response.json()

        except Exception as e:
            self.logger.error(f"Perplexity API error: {str(e)}")
            return {"error": str(e)}

    async def _get_web_data(self, query: str) -> Dict[str, Any]:
        """Get real-time data from web scraping"""
        try:
            async with aiohttp.ClientSession() as session:
                # Scrape dealership website for current info
                urls = [
                    "https://www.jackingram.com/new-inventory/",
                    "https://www.jackingram.com/service-specials/",
                    "https://www.jackingram.com/current-offers/",
                ]

                data = {}
                for url in urls:
                    async with session.get(url) as response:
                        _ = await response.text()
                        # Parse HTML and extract relevant info in production
                        data[url] = "Web data placeholder"

                return data

        except Exception as e:
            self.logger.error(f"Web scraping error: {str(e)}")
            return {"error": str(e)}

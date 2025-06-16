"""
# mypy: ignore-errors
FireCrawl integration for real-time website data
"""

import aiohttp
import logging
from typing import Dict, Any


class FireCrawlClient:
    """Client for FireCrawl web scraping"""

    def __init__(self, api_key: str = "fc-be236bbbb1ae48a7b516efb3a2d932e2"):
        self.api_key = api_key
        self.base_url = "https://api.firecrawl.com/v1"
        self.logger = logging.getLogger(__name__)

    async def crawl_dealership_sites(self) -> Dict[str, Any]:
        """
        Crawl all Jack Ingram dealership sites for current information

        Returns:
            Dict containing inventory, offers, and other real-time data
        """
        sites = [
            "https://www.jackingram.com",
            "https://www.jackingramnissan.com",
            "https://www.jackingramaudi.com",
            "https://www.jackingram-mercedesbenz.com",
            "https://www.jackingram-porsche.com",
            "https://www.jackingram-vw.com",
        ]

        results = {}

        try:
            async with aiohttp.ClientSession() as session:
                for site in sites:
                    # Crawl inventory pages
                    inventory_data = await self._crawl_page(
                        session,
                        f"{site}/inventory",
                        selectors={
                            "vehicles": ".vehicle-card",
                            "prices": ".price",
                            "offers": ".special-offer",
                        },
                    )

                    # Crawl specials/offers pages
                    offers_data = await self._crawl_page(
                        session,
                        f"{site}/specials",
                        selectors={
                            "offers": ".offer-card",
                            "expiration": ".expiration-date",
                            "details": ".offer-details",
                        },
                    )

                    brand = site.split("jackingram")[-1].strip("-.com")
                    results[brand] = {
                        "inventory": inventory_data,
                        "offers": offers_data,
                    }

        except Exception as e:
            self.logger.error(f"Error crawling dealership sites: {str(e)}")

        return results

    async def _crawl_page(
        self, session: aiohttp.ClientSession, url: str, selectors: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Crawl a specific page using FireCrawl

        Args:
            session: aiohttp ClientSession
            url: URL to crawl
            selectors: CSS selectors to extract

        Returns:
            Dict containing extracted data
        """
        try:
            async with session.post(
                f"{self.base_url}/crawl",
                json={
                    "url": url,
                    "selectors": selectors,
                    "wait_for": list(selectors.values()),
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as response:
                return await response.json()

        except Exception as e:
            self.logger.error(f"Error crawling {url}: {str(e)}")
            return {}

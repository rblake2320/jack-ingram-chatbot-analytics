"""
Perplexity API client for real-time information
"""

import aiohttp
import logging
from typing import Dict, Any, Optional
from datetime import datetime

class PerplexityClient:
    """Client for Perplexity API integration"""
    
    def __init__(self, api_key: str = "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"):
        self.api_key = api_key
        self.base_url = "https://api.perplexity.ai"
        self.logger = logging.getLogger(__name__)
        
    async def get_realtime_info(self, query: str) -> Dict[str, Any]:
        """
        Get real-time information from Perplexity
        
        Args:
            query: The query to get information about
            
        Returns:
            Dict containing real-time information
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "accept": "application/json",
                        "content-type": "application/json",
                        "Authorization": f"Bearer {self.api_key}"
                    },
                    json={
                        "model": "sonar-pro",
                        "messages": [
                            {
                                "role": "system",
                                "content": f"""Current date: {datetime.now().strftime('%B %d, %Y')}
                                Provide accurate, real-time information about Jack Ingram Motors dealerships."""
                            },
                            {
                                "role": "user",
                                "content": query
                            }
                        ]
                    }
                ) as response:
                    response_data = await response.json()
                    
                    return {
                        "response": response_data.get("choices", [{}])[0].get("message", {}).get("content", ""),
                        "metadata": {
                            "model": response_data.get("model", ""),
                            "timestamp": datetime.now().isoformat()
                        }
                    }
                    
        except Exception as e:
            self.logger.error(f"Perplexity API error: {str(e)}")
            return {
                "error": str(e),
                "metadata": {
                    "timestamp": datetime.now().isoformat()
                }
            }
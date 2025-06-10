"""
API Router to manage requests between UI and endpoints
"""

import logging
import asyncio
from datetime import datetime
import pytz
from typing import Dict, Any, Optional
from api_gateway import APIGateway
from claude_client import ClaudeClient
from perplexity_client import PerplexityClient

class APIRouter:
    """Router for managing API requests"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.gateway = APIGateway()
        self.claude = ClaudeClient()
        self.perplexity = PerplexityClient()
        
    async def process_request(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process incoming requests and route to appropriate endpoints
        
        Args:
            message: User's message
            context: Additional context like session info
            
        Returns:
            Combined response from all endpoints
        """
        try:
            # Extract vehicle query parameters
            query = self.extract_vehicle_params(message)
            
            # Get data from multiple sources
            vehicle_data = {}
            perplexity_data = {}
            
            if query:
                # Run API calls concurrently
                vehicle_data = await self.gateway.get_vehicle_data(query)
                perplexity_data = await self.perplexity.get_realtime_info(message)
            
            # Enhance Claude prompt with real-time data
            enhanced_context = {
                "vehicle_data": vehicle_data,
                "realtime_info": perplexity_data,
                "session": context.get("session", {}) if context else {}
            }
            
            # Get responses from both LLMs
            claude_response, perplexity_response = await asyncio.gather(
                self.claude.send_message(message, context=enhanced_context),
                self.perplexity.get_realtime_info(message)
            )
            
            # Combine responses with priority to real-time info
            final_response = {
                "response": claude_response.get("response", ""),
                "conversation_id": claude_response.get("conversation_id", ""),
                "realtime_data": perplexity_response.get("response", ""),
                "timestamp": datetime.now(pytz.timezone('America/Chicago')).strftime('%B %d, %Y %H:%M:%S %Z')
            }
            
            # Combine LLM responses with real-time info
            current_time = datetime.now(pytz.timezone('America/Chicago'))
            
            if "date" in message.lower() or "time" in message.lower():
                final_response["response"] = f"Today's date is {current_time.strftime('%B %d, %Y')} {current_time.strftime('%Z')}"
            
            return final_response
            
        except Exception as e:
            self.logger.error(f"Error processing request: {str(e)}")
            return {
                "error": "Failed to process request",
                "details": str(e)
            }
            
    def extract_vehicle_params(self, message: str) -> Dict[str, Any]:
        """Extract vehicle-related parameters from message"""
        # Simple extraction - could be enhanced with NLP
        params = {}
        
        makes = ["nissan", "audi", "mercedes", "porsche", "volkswagen", "volvo"]
        message = message.lower()
        
        # Extract make
        for make in makes:
            if make in message:
                params["make"] = make
                break
                
        # TODO: Add model and year extraction
        
        return params
"""
API Router to manage requests between UI and endpoints
"""

import logging
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
            
            # Get Claude response
            claude_response = await self.claude.send_message(
                message,
                context=enhanced_context
            )
            
            return {
                "response": claude_response.get("response", ""),
                "data": vehicle_data,
                "conversation_id": claude_response.get("conversation_id", "")
            }
            
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
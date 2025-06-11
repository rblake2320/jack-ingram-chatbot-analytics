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
from realtime_client import RealtimeClient
from knowledge_base import KnowledgeBase

class APIRouter:
    """Router for managing API requests"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.gateway = APIGateway()
        self.claude = ClaudeClient()
        self.realtime = RealtimeClient()
        self.knowledge = KnowledgeBase()
        
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
            # Check cache for common queries
            cached_response = self.knowledge.get_cached_response(message.lower())
            if cached_response:
                return {"response": cached_response, "source": "cache"}
                
            # Extract query parameters
            query = self.extract_vehicle_params(message)
            
            # Get dealership info if relevant
            dealership_info = {}
            brand = query.get("make") if query else None
            
            if any(keyword in message.lower() for keyword in ["hours", "location", "contact", "about", "services"]):
                category = next((k for k in ["hours", "services"] if k in message.lower()), "main")
                dealership_info = self.knowledge.get_dealership_info(category, brand)
                
                # Cache and return formatted dealership info
                if dealership_info:
                    response = self.format_dealership_response(dealership_info, category)
                    self.knowledge.cache_response(message.lower(), response)
                    return {"response": response, "source": "knowledge_base"}
            
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
            
            # Get real-time data and Claude response concurrently
            realtime_data, claude_response = await asyncio.gather(
                self.realtime.get_realtime_info(message),
                self.claude.send_message(message, context=enhanced_context)
            )
            
            # Use real-time data for time-sensitive queries
            if "date" in message.lower() or "time" in message.lower():
                return {
                    "response": f"Today's date and time is {realtime_data['current_time']}",
                    "source": "realtime"
                }
            
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
            
    def format_dealership_response(self, info: Dict[str, Any], category: str) -> str:
        """Format dealership information into a response"""
        if category == "hours":
            return f"""
Sales Hours:
{self.knowledge.format_hours('sales')}

Service Hours:
{self.knowledge.format_hours('service')}
"""
        elif category == "services":
            services = info.get("services", {})
            response = "Our services include:\n"
            for dept, service_list in services.items():
                response += f"\n{dept.title()}:\n"
                response += "\n".join(f"- {service}" for service in service_list)
            return response
        else:
            main_info = info.get("main", {})
            return f"""
{main_info.get('name', 'Jack Ingram Motors')}
{main_info.get('about', '')}

Location: {main_info.get('location', '')}
Phone: {main_info.get('phone', '')}
Website: {main_info.get('website', '')}
"""

    def extract_vehicle_params(self, message: str) -> Dict[str, Any]:
        """Extract vehicle-related parameters from message"""
        params = {}
        message = message.lower()
        
        # Extract brand/make
        makes = ["nissan", "audi", "mercedes", "porsche", "volkswagen", "volvo"]
        for make in makes:
            if make in message:
                params["make"] = make
                # Get brand-specific tone for responses
                params["tone"] = self.knowledge.get_brand_tone(make)
                # Get popular models for the brand
                params["models"] = self.knowledge.get_brand_models(make)
                break
        
        # Extract common topics
        topics = ["inventory", "price", "test drive", "service", "special", "offer"]
        for topic in topics:
            if topic in message:
                params["topic"] = topic
                break
        
        return params
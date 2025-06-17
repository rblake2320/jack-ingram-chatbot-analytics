"""
API client for interacting with the Anthropic Claude API with enhanced error handling
"""

import json
import httpx  # Added httpx
import logging
from typing import Dict, List, Any, Optional
from config import (
    ANTHROPIC_API_URL,
    ANTHROPIC_VERSION,
    MODEL,
    SYSTEM_PROMPT
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ClaudeClient:
    """Client for interacting with Anthropic's Claude API with improved error handling"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Claude client with API credentials"""
        from config import ANTHROPIC_API_KEY
        from demo.mcp_client import MCPClient # Ensuring MCPClient is available

        resolved_api_key = api_key or ANTHROPIC_API_KEY
        if not resolved_api_key:
            error_message = "Anthropic API key not found. Please set ANTHROPIC_API_KEY environment variable."
            logger.critical(error_message)
            raise ValueError(error_message)

        self.api_url = ANTHROPIC_API_URL
        self.headers = {
            "x-api-key": resolved_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        self.system_prompt = SYSTEM_PROMPT
        self.model = MODEL
        self.conversation_history: List[Dict[str, str]] = []
    
    async def send_message(self, user_message: str, max_tokens: int = 1024) -> Dict[str, Any]: # Changed to async def
        """
        Send a message to Claude and get a response with enhanced error handling
        
        Args:
            user_message: The user's message text
            max_tokens: Maximum number of tokens in the response
            
        Returns:
            Dict containing the response and metadata
        """
        try:
            # Get real-time context from MCP
            mcp_client = MCPClient() # MCPClient will be in scope due to import in __init__
            realtime_info = await mcp_client.get_realtime_info(user_message) # await is now correct
            
            # Enhance user message with real-time context
            enhanced_message = f"""User message: {user_message}

Available real-time information:
- Current inventory: {realtime_info.get('inventory', {})}
- Service availability: {realtime_info.get('service', {})}
- Latest offers: {realtime_info.get('offers', {})}
- Related updates: {realtime_info.get('search', {})}
"""
            
            # Send request to API
            logger.info(f"Sending request to Claude API: {user_message[:50]}...")
            
            payload = {
                "model": self.model,
                "max_tokens": max_tokens,
                "system": self.system_prompt,
                "messages": self.conversation_history + [
                    {"role": "user", "content": enhanced_message}
                ]
            }
            
            async with httpx.AsyncClient() as client: # Replaced requests.post with httpx.AsyncClient
                response = await client.post(
                    self.api_url,
                    headers=self.headers,
                    json=payload,
                    timeout=30.0 # Added timeout
                )
            
            # Log the full response for debugging
            logger.info(f"API Response Status: {response.status_code}")
            logger.info(f"API Response Headers: {response.headers}")
            
            # Check for authentication errors specifically
            if response.status_code == 401:
                error_data = response.json() # httpx response.json() works similarly
                error_message = error_data.get("error", {}).get("message", "Authentication failed")
                logger.error(f"Authentication error: {error_message}")
                return {
                    "response": f"I'm experiencing an authentication issue with the Claude API. Error: {error_message}. Please contact support with this information.",
                    "error": error_message,
                    "status_code": 401
                }
            
            # Check for other error status codes
            response.raise_for_status() # httpx response.raise_for_status() works similarly
            response_data = response.json() # httpx response.json() works similarly
            
            # Extract the assistant's message
            content_list = response_data.get("content", [])
            assistant_message = ""
            for content in content_list:
                if content.get("type") == "text":
                    assistant_message += content.get("text", "")
            
            if not assistant_message:
                assistant_message = "Sorry, I couldn't process your request."
            
            # Update conversation history
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": assistant_message})
            
            return {
                "response": assistant_message,
                "conversation_id": response_data.get("id", ""),
                "model": response_data.get("model", self.model),
                "usage": response_data.get("usage", {})
            }
            
        except httpx.HTTPStatusError as e: # Changed to httpx.HTTPStatusError
            logger.error(f"HTTP Error: {str(e)}")
            status_code = e.response.status_code
            error_detail = ""
            
            # Try to extract error details from response
            try:
                error_json = e.response.json() if hasattr(e, 'response') else {}
                error_detail = json.dumps(error_json)
                logger.error(f"Error details: {error_detail}")
            except:
                error_detail = str(e)
            
            return {
                "response": f"I encountered an error communicating with the Claude API (HTTP {status_code}). Technical details: {error_detail}",
                "error": str(e),
                "status_code": status_code
            }
            
        except httpx.RequestError as e: # Changed to httpx.RequestError
            logger.error(f"Request Error: {str(e)}")
            return {
                "response": f"I'm having trouble connecting to the Claude API. Technical details: {str(e)}",
                "error": str(e)
            }
        
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {
                "response": "I encountered an unexpected error. Please try again later or contact support.",
                "error": str(e)
            }
    
    def reset_conversation(self) -> None:
        """Reset the conversation history"""
        self.conversation_history = []
        logger.info("Conversation history has been reset")
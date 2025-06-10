"""
API client for interacting with the Anthropic Claude API
"""

import json
import requests
import logging
from typing import Dict, List, Any, Optional
from .config import (
    ANTHROPIC_API_URL,
    ANTHROPIC_VERSION,
    MODEL,
    SYSTEM_PROMPT
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ClaudeClient:
    """Client for interacting with Anthropic's Claude API"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Claude client with API credentials"""
        from .config import ANTHROPIC_API_KEY
        self.api_url = ANTHROPIC_API_URL
        self.headers = {
            "x-api-key": api_key or ANTHROPIC_API_KEY,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json"
        }
        self.system_prompt = SYSTEM_PROMPT
        self.model = MODEL
        self.conversation_history: List[Dict[str, str]] = []
    
    def send_message(self, user_message: str, max_tokens: int = 1024) -> Dict[str, Any]:
        """
        Send a message to Claude and get a response
        
        Args:
            user_message: The user's message text
            max_tokens: Maximum number of tokens in the response
            
        Returns:
            Dict containing the response and metadata
        """
        # Add user message to conversation history
        self.conversation_history.append({"role": "user", "content": user_message})
        
        # Prepare the request payload
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": self.system_prompt,
            "messages": self.conversation_history
        }
        
        try:
            # Send the request to the API
            logger.info(f"Sending request to Claude API: {user_message[:50]}...")
            response = requests.post(
                self.api_url,
                headers=self.headers,
                data=json.dumps(payload)
            )
            
            # Check for successful response
            response.raise_for_status()
            response_data = response.json()
            
            # Extract the assistant's message
            assistant_message = response_data.get("content", [{"text": "Sorry, I couldn't process your request."}])[0]["text"]
            
            # Add assistant response to conversation history
            self.conversation_history.append({"role": "assistant", "content": assistant_message})
            
            return {
                "response": assistant_message,
                "conversation_id": response_data.get("id", ""),
                "model": response_data.get("model", self.model),
                "usage": response_data.get("usage", {})
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error communicating with Claude API: {str(e)}")
            error_message = f"Error: {str(e)}"
            return {
                "response": "I'm sorry, I encountered an error while processing your request. Please try again later.",
                "error": error_message
            }
    
    def reset_conversation(self) -> None:
        """Reset the conversation history"""
        self.conversation_history = []
        logger.info("Conversation history has been reset")

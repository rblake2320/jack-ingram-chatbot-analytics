"""
Test script for the Jack Ingram Motors Chatbot Demo with corrected imports
"""

import os
import sys
import json
import unittest
import httpx # Added httpx
import asyncio # Added asyncio
from unittest.mock import patch, MagicMock, AsyncMock # Added AsyncMock

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Now import the modules
from src.demo.claude_client import ClaudeClient
from src.demo.config import ANTHROPIC_API_KEY, ANTHROPIC_API_URL

@patch('src.demo.claude_client.MCPClient') # Patch MCPClient where claude_client looks for it
class TestClaudeClient(unittest.IsolatedAsyncioTestCase): # Changed inheritance
    """Test the Claude API client functionality"""
    
    def setUp(self, mock_mcp_client_constructor): # mock_mcp_client_constructor is from class patch
        """Set up test environment"""
        # Configure the mock MCPClient instance
        self.mock_mcp_instance = mock_mcp_client_constructor.return_value
        self.mock_mcp_instance.get_realtime_info = AsyncMock(return_value={
            "inventory": "mocked_inventory",
            "service": "mocked_service",
            "offers": "mocked_offers",
            "search": "mocked_search"
        })

        self.client = ClaudeClient() # ClaudeClient will use the mocked MCPClient
        self.test_message = "Test message"
    
    @patch('httpx.AsyncClient.post') # Changed to httpx.AsyncClient.post
    async def test_send_message_success(self, mock_httpx_post, mock_mcp_client_constructor_class): # mock_httpx_post is from method patch
        """Test successful message sending"""
        # Mock successful response for httpx
        mock_response = MagicMock() # This mock represents the response object from httpx
        mock_response.status_code = 200
        mock_response.json.return_value = { # This is what response.json() will return
            "id": "test_id",
            "model": "claude-3-opus-20240229",
            "content": [{"text": "Test response"}],
            "usage": {"input_tokens": 10, "output_tokens": 5}
        }
        # httpx.AsyncClient.post is an async method, its return value is the response.
        # So mock_httpx_post itself should be an AsyncMock, or its return_value configured to be awaitable.
        # @patch makes it an AsyncMock if the original is async.
        # We need to set the return_value of this AsyncMock.
        mock_httpx_post.return_value = mock_response
        
        # Call the method
        response = await self.client.send_message(self.test_message) # Added await
        
        # Assertions
        self.assertEqual(response["response"], "Test response")
        self.assertEqual(response["model"], "claude-3-opus-20240229")
        self.assertEqual(len(self.client.conversation_history), 2)  # User + assistant messages
        
        # Verify API call
        mock_httpx_post.assert_called_once()
        call_args = mock_httpx_post.call_args
        self.assertEqual(call_args.args[0], ANTHROPIC_API_URL) # httpx uses args[0] for URL
        self.assertIn("x-api-key", call_args.kwargs["headers"])
        self.assertEqual(call_args.kwargs["headers"]["x-api-key"], ANTHROPIC_API_KEY)
    
    @patch('httpx.AsyncClient.post') # Changed to httpx.AsyncClient.post
    async def test_send_message_error(self, mock_httpx_post, mock_mcp_client_constructor_class): # mock_httpx_post from method patch
        """Test error handling in message sending"""
        # Mock error response for httpx
        mock_httpx_post.side_effect = httpx.RequestError("Test error") # Using httpx exception
        
        # Call the method
        response = await self.client.send_message(self.test_message) # Added await
        
        # Assertions
        self.assertIn("I'm having trouble connecting to the Claude API", response["response"]) # Error message changed in claude_client
        self.assertIn("error", response)
        # Conversation history might still have the user message if MCPClient call succeeded
        # Let's check the implementation of claude_client.py for history update on error
        # Current claude_client.py adds user message to history *after* successful API call.
        # So, if API call fails, only user message should not be there.
        # However, the MCPClient call happens before, and if it succeeds, it might add to history.
        # The current test structure for claude_client.py doesn't show history modification before API call.
        # The prompt's claude_client.py adds to history only *after* successful API call.
        # In the case of RequestError, nothing is added.
        self.assertEqual(len(self.client.conversation_history), 0)
    
    def test_reset_conversation(self):
        """Test conversation reset"""
        # Add messages to history
        self.client.conversation_history = [ # This client is from setUp, so MCPClient is already mocked
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"}
        ]
        
        # Reset conversation
        self.client.reset_conversation()
        
        # Assert history is empty
        self.assertEqual(len(self.client.conversation_history), 0)

@patch('src.demo.claude_client.MCPClient') # Patch MCPClient for this class too
class TestSecurityFeatures(unittest.IsolatedAsyncioTestCase): # Changed inheritance
    """Test security features of the chatbot demo"""
    
    def setUp(self, mock_mcp_client_constructor): # mock_mcp_client_constructor is from class patch
        """Set up test environment for security tests"""
        self.mock_mcp_instance = mock_mcp_client_constructor.return_value
        self.mock_mcp_instance.get_realtime_info = AsyncMock(return_value={
            "inventory": "mocked_inventory",
            # ... other mcp data ...
        })
        # This client is used by test_api_key_handling and test_input_validation
        self.client = ClaudeClient()

    def test_api_key_handling(self, mock_mcp_client_constructor_class): # Comes from class patch
        """Test API key is handled securely"""
        # API key should not be hardcoded in source files (except config for demo purposes)
        # In production, this would be loaded from environment variables
        
        # Check that API key is not exposed in client instance dict
        # self.client is already created in setUp with mocked MCPClient
        client_dict = self.client.__dict__
        
        # API key should only be in headers, not as a separate attribute
        api_key_count = 0
        for key, value in client_dict.items():
            if key != "headers" and isinstance(value, str) and value == ANTHROPIC_API_KEY:
                api_key_count += 1
        
        self.assertEqual(api_key_count, 0, "API key should not be exposed in client attributes")
    
    @patch('httpx.AsyncClient.post') # Patch httpx for send_message
    async def test_input_validation(self, mock_httpx_post, mock_mcp_client_constructor_class): # mock_httpx_post from method, mcp from class
        """Test input validation for security"""
        # self.client is already created in setUp with mocked MCPClient
        
        # Test with various inputs
        test_cases = [
            "",  # Empty string
            "A" * 10000,  # Very long string
            "<script>alert('XSS')</script>",  # XSS attempt
            "'; DROP TABLE users; --",  # SQL injection attempt
        ]
        
        for test_input in test_cases:
            # No exceptions should be raised by send_message logic itself
            # Configure mock_httpx_post for successful API interaction
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"content": [{"text": "Response"}]}
            mock_httpx_post.return_value = mock_response

            try:
                await self.client.send_message(test_input) # Added await
                # If we get here, no exception was raised by our code
                self.assertTrue(True)
            except Exception as e:
                # This fail is if our client's send_message itself fails, not the API call mock.
                self.fail(f"Input validation failed for: {test_input}. Error: {str(e)}")

if __name__ == "__main__":
    unittest.main()

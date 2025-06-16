"""
# mypy: ignore-errors
Test script for the Jack Ingram Motors Chatbot Demo with corrected imports
"""

import os
import sys
import unittest
import asyncio
import requests
from unittest.mock import patch, MagicMock

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Now import the modules
from src.demo.claude_client import ClaudeClient
from src.demo.config import ANTHROPIC_API_KEY, ANTHROPIC_API_URL


class TestClaudeClient(unittest.TestCase):
    """Test the Claude API client functionality"""

    def setUp(self):
        """Set up test environment"""
        self.client = ClaudeClient()
        self.test_message = "Test message"

    @patch("src.demo.mcp_client.MCPClient.get_realtime_info", return_value={})
    @patch("requests.post")
    def test_send_message_success(self, mock_post, mock_mcp):
        """Test successful message sending"""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test_id",
            "model": "claude-3-opus-20240229",
            "content": [{"type": "text", "text": "Test response"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_post.return_value = mock_response

        # Call the method
        response = asyncio.run(self.client.send_message(self.test_message))

        # Assertions
        self.assertEqual(response["response"], "Test response")
        self.assertEqual(response["model"], "claude-3-opus-20240229")
        self.assertEqual(
            len(self.client.conversation_history), 2
        )  # User + assistant messages

        # Verify API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], ANTHROPIC_API_URL)
        self.assertIn("x-api-key", call_args[1]["headers"])
        self.assertEqual(call_args[1]["headers"]["x-api-key"], ANTHROPIC_API_KEY)

    @patch("src.demo.mcp_client.MCPClient.get_realtime_info", return_value={})
    @patch("requests.post")
    def test_send_message_error(self, mock_post, mock_mcp):
        """Test error handling in message sending"""
        # Mock error response
        mock_post.side_effect = requests.exceptions.RequestException("Test error")

        # Call the method
        response = asyncio.run(self.client.send_message(self.test_message))

        # Assertions
        self.assertIn("trouble", response["response"])
        self.assertIn("error", response)
        self.assertEqual(len(self.client.conversation_history), 0)

    def test_reset_conversation(self):
        """Test conversation reset"""
        # Add messages to history
        self.client.conversation_history = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
        ]

        # Reset conversation
        self.client.reset_conversation()

        # Assert history is empty
        self.assertEqual(len(self.client.conversation_history), 0)


class TestSecurityFeatures(unittest.TestCase):
    """Test security features of the chatbot demo"""

    def test_api_key_handling(self):
        """Test API key is handled securely"""
        # API key should not be hardcoded in source files (except config for demo purposes)
        # In production, this would be loaded from environment variables

        # Check that API key is not exposed in client instance dict
        client = ClaudeClient()
        client_dict = client.__dict__

        # API key should only be in headers, not as a separate attribute
        api_key_count = 0
        for key, value in client_dict.items():
            if (
                key != "headers"
                and isinstance(value, str)
                and value == ANTHROPIC_API_KEY
            ):
                api_key_count += 1

        self.assertEqual(
            api_key_count, 0, "API key should not be exposed in client attributes"
        )

    def test_input_validation(self):
        """Test input validation for security"""
        client = ClaudeClient()

        # Test with various inputs
        test_cases = [
            "",  # Empty string
            "A" * 10000,  # Very long string
            "<script>alert('XSS')</script>",  # XSS attempt
            "'; DROP TABLE users; --",  # SQL injection attempt
        ]

        for test_input in test_cases:
            # No exceptions should be raised
            try:
                # We're not actually sending to API, just checking handling
                with patch("requests.post") as mock_post:
                    mock_response = MagicMock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        "content": [{"text": "Response"}]
                    }
                    mock_post.return_value = mock_response

                    asyncio.run(client.send_message(test_input))
                    # If we get here, no exception was raised
                    self.assertTrue(True)
            except Exception as e:
                self.fail(f"Input validation failed for: {test_input}. Error: {str(e)}")


if __name__ == "__main__":
    unittest.main()

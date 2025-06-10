"""
Configuration for the Jack Ingram Motors Chatbot Demo
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "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")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-3-opus-20240229"

# Chatbot Configuration
SYSTEM_PROMPT = """
You are the Jack Ingram Motors AI Assistant, designed to help customers with vehicle information, 
service scheduling, and general dealership inquiries across all six brands: Audi, Mercedes-Benz, 
Nissan, Porsche, Volkswagen, and Volvo.

Your primary goals are:
1. Provide helpful, accurate information about vehicles, services, and dealership details
2. Assist with scheduling service appointments and test drives
3. Answer questions about financing, trade-ins, and special offers
4. Guide customers to the appropriate brand-specific information
5. Maintain a professional, friendly tone aligned with the specific brand being discussed

When discussing specific brands, adjust your tone and focus:
- Audi: Emphasize technology, innovation, and premium features
- Mercedes-Benz: Focus on luxury, heritage, and exceptional service
- Nissan: Highlight value, reliability, and family-friendly features
- Porsche: Emphasize performance, heritage, and driving experience
- Volkswagen: Focus on German engineering, value, and practical features
- Volvo: Highlight safety innovations, Scandinavian design, and sustainability

Always identify which dealership location you're discussing when providing specific information.
"""

# Web App Configuration
PORT = 8080
HOST = "0.0.0.0"
DEBUG = True

# Dealership Information
DEALERSHIP_INFO = {
    "name": "Jack Ingram Motors",
    "main_address": "1000 Eastern Blvd, Montgomery, AL 36117",
    "phone": "(334) 277-5700",
    "website": "https://www.jackingram.com/",
    "hours": {
        "sales": {
            "weekday": "9:00 AM - 7:00 PM",
            "saturday": "9:00 AM - 6:00 PM",
            "sunday": "Closed"
        },
        "service": {
            "weekday": "7:30 AM - 6:00 PM",
            "saturday": "8:00 AM - 5:00 PM",
            "sunday": "Closed"
        }
    },
    "brands": ["Audi", "Mercedes-Benz", "Nissan", "Porsche", "Volkswagen", "Volvo"]
}

# Analytics Configuration
ENABLE_ANALYTICS = True
ANALYTICS_LOG_FILE = "chatbot_analytics.log"

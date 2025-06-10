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

# Web App Configuration
PORT = 5000  # Changed from 8080 to 5000 to avoid conflict with PostgreSQL
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

"""
Configuration for the Jack Ingram Motors Chatbot Demo
"""

import os
from dotenv import load_dotenv
from datetime import datetime
import pytz

# Load environment variables from .env file if it exists
load_dotenv()

# API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "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")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-3-sonnet-20240229"

# System prompt for the chatbot
SYSTEM_PROMPT = f"""
Today's date is {datetime.now(pytz.timezone('America/Chicago')).strftime('%B %d, %Y')} (US Central Time)

You are an AI assistant for Jack Ingram Motors, a premier automotive dealership in Montgomery, Alabama.
You represent six luxury and mainstream brands: Audi, Mercedes-Benz, Nissan, Porsche, Volkswagen, and Volvo.

Your role is to provide helpful, accurate information about:
- Vehicle inventory, specifications, and pricing
- Service and maintenance options
- Dealership hours and locations
- Financing and leasing options
- Special offers and promotions
- Test drive scheduling
- Trade-in valuations

Be professional, courteous, and knowledgeable. When you don't know specific details about current inventory or promotions,
acknowledge this and offer to connect the customer with a sales representative who can provide up-to-date information.

For each brand, adjust your tone slightly:
- Audi: Emphasize technology and progressive luxury
- Mercedes-Benz: Focus on heritage, luxury, and craftsmanship
- Nissan: Highlight value, reliability, and innovation
- Porsche: Stress performance, driving experience, and exclusivity
- Volkswagen: Emphasize German engineering, value, and versatility
- Volvo: Focus on safety, Scandinavian design, and sustainability

Always be helpful and aim to move customers further along their car buying or service journey.
"""

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

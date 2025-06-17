"""
Web application for the Jack Ingram Motors Chatbot Demo
"""

import os
import json
import logging
from datetime import datetime
import pytz
from flask import Flask, request, jsonify, render_template, session
import asyncio
from concurrent.futures import ThreadPoolExecutor
from api_router import APIRouter
from config import PORT, HOST, DEBUG, ENABLE_ANALYTICS, ANALYTICS_LOG_FILE, DEALERSHIP_INFO

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, static_url_path='', static_folder='static')
app.secret_key = os.urandom(24)  # For session management

# Initialize API router
api_router = APIRouter()

# Analytics tracking
def log_interaction(user_message, assistant_response, metadata=None):
    """Log user-assistant interactions for analytics"""
    if not ENABLE_ANALYTICS:
        return
    
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "user_message": user_message,
        "assistant_response": assistant_response,
        "metadata": metadata or {}
    }
    
    try:
        with open(ANALYTICS_LOG_FILE, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        logger.error(f"Error logging analytics: {str(e)}")

@app.route('/')
def index():
    """Render the main chatbot interface"""
    return render_template('index.html', dealership_info=DEALERSHIP_INFO)

@app.route('/api/chat', methods=['POST'])
def chat():
    """API endpoint for chatbot interactions"""
    data = request.json
    user_message = data.get('message', '')
    
    if not user_message:
        return jsonify({"error": "No message provided"}), 400
    
    # Get conversation ID from session or create new one
    conversation_id = session.get('conversation_id')
    if not conversation_id:
        # Reset conversation for new sessions
        api_router.claude.reset_conversation()
        session['conversation_id'] = f"conv_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    try:
        # Process message through API router
        # asyncio.run() is suitable for calling async code from sync code
        # It handles loop creation and closing implicitly.
        response_data = asyncio.run(api_router.process_request(
            user_message,
            context={"session": session}
        ))
        
        # Log interaction for analytics
        metadata = {
            "conversation_id": session.get('conversation_id'),
            "timestamp": datetime.now().isoformat(),
            "user_agent": request.headers.get('User-Agent'),
            "usage": response_data.get("usage", {})
        }
        log_interaction(user_message, response_data.get("response", ""), metadata)
        
        return jsonify({
            "response": response_data.get("response", "I'm sorry, I couldn't process your request."),
            "conversation_id": session.get('conversation_id')
        })
        
    except Exception as e:
        logger.error(f"Error in /api/chat: {str(e)}")
        return jsonify({"error": "An internal server error occurred"}), 500

@app.route('/api/reset', methods=['POST'])
def reset_conversation():
    """Reset the conversation history"""
    api_router.claude.reset_conversation()
    session['conversation_id'] = f"conv_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return jsonify({"status": "success", "message": "Conversation reset"})

@app.route('/api/dealership-info', methods=['GET'])
def get_dealership_info():
    """Return dealership information"""
    return jsonify(DEALERSHIP_INFO)

@app.route('/health')
def health_check():
    """Health check endpoint for DigitalOcean App Platform"""
    return jsonify({"status": "healthy"}), 200

def run_app():
    """Run the Flask application"""
    app.run(host=HOST, port=PORT, debug=DEBUG)

if __name__ == "__main__":
    run_app()

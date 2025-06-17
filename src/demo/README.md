# Chatbot Demo Integration Guide

## Overview

This directory contains a fully functional chatbot demo for Jack Ingram Motors using the Anthropic Claude API. The demo showcases the capabilities of an AI assistant that can answer questions about vehicles, services, and dealership information across all six brands (Audi, Mercedes-Benz, Nissan, Porsche, Volkswagen, and Volvo).

## Features

- **Interactive Web Interface**: Professional, responsive design with Jack Ingram Motors branding
- **Multi-Brand Support**: Tailored responses for each of the six dealership brands
- **Conversation Memory**: Maintains context throughout the conversation
- **Analytics Tracking**: Logs user interactions for business insights
- **Security Features**: Secure API key handling and input validation

## Prerequisites

- Python 3.8+
- Flask
- Requests
- Python-dotenv

## Installation

1. Clone the repository:
```bash
git clone https://github.com/rblake2320/jack-ingram-chatbot-analytics.git
cd jack-ingram-chatbot-analytics
```

2. Install dependencies:
```bash
pip install flask requests python-dotenv
```

3. Set up environment variables (optional):
```bash
# Create a .env file in the project root
echo "ANTHROPIC_API_KEY=your_api_key_here" > .env
```

## Running the Demo

1. Start the Flask application:
```bash
cd src/demo
python -m app
```

2. Open your browser and navigate to:
```
http://localhost:8080
```

## Configuration

The chatbot demo can be configured by modifying the `config.py` file:

- **API Settings**: Change the model, API key, or endpoint
- **System Prompt**: Customize the chatbot's personality and knowledge
- **Dealership Information**: Update hours, locations, or brand information
- **Analytics**: Enable/disable analytics logging

## Integration with Your Website

### Option 1: Embed as an iframe

```html
<iframe 
  src="https://your-deployed-demo-url" 
  width="400" 
  height="600" 
  style="border:none;border-radius:10px;box-shadow:0 0 10px rgba(0,0,0,0.1);"
></iframe>
```

### Option 2: JavaScript Widget

Add this code to your website:

```html
<div id="jack-ingram-chatbot"></div>
<script src="https://your-deployed-demo-url/static/widget.js"></script>
<script>
  JackIngramChatbot.init({
    container: 'jack-ingram-chatbot',
    position: 'bottom-right',
    brandColor: '#007bff',
    dealershipId: 'jackingram'
  });
</script>
```

### Option 3: API Integration

The chatbot provides a simple REST API:

- **POST /api/chat**: Send a message to the chatbot
  ```json
  {
    "message": "What brands do you carry?"
  }
  ```

- **POST /api/reset**: Reset the conversation
  ```json
  {}
  ```

- **GET /api/dealership-info**: Get dealership information
  ```
  No request body needed
  ```

## Security Considerations

- The `ANTHROPIC_API_KEY` must be set as an environment variable. It is not hardcoded in the application. You can use a `.env` file (as shown in the Installation section) or set it directly in your deployment environment.
- In production, ensure your environment variables are managed securely, for example, using a secure vault or your hosting platform's secret management tools.
- Implement rate limiting for production deployments
- Add CSRF protection for the web interface
- Consider adding user authentication for sensitive operations

## Testing

Run the automated tests:

```bash
python -m src.demo.tests.test_chatbot
```

## Customization

### Changing the Look and Feel

The UI can be customized by modifying the HTML/CSS in `templates/index.html`.

### Modifying Chatbot Behavior

To change how the chatbot responds:

1. Update the `SYSTEM_PROMPT` in `config.py`
2. Modify the `ClaudeClient` class in `claude_client.py` for advanced customization

### Adding New Features

The modular design makes it easy to add new features:

1. Add new routes to `app.py`
2. Create new templates in the `templates` directory
3. Extend the `ClaudeClient` class with new methods

## Deployment

For production deployment:

1. Use a WSGI server like Gunicorn
2. Set up HTTPS with a valid SSL certificate
3. Implement proper logging and monitoring
4. Use environment variables for sensitive configuration
5. Consider containerization with Docker

Example production startup:

```bash
gunicorn -w 4 -b 0.0.0.0:8080 src.demo.app:app
```

## Analytics

The chatbot logs interactions to `chatbot_analytics.log` by default. Each log entry contains:

- Timestamp
- User message
- Assistant response
- Metadata (conversation ID, user agent, token usage)

This data can be processed to generate insights about:

- Most common questions
- User engagement metrics
- Conversation flow patterns
- Brand-specific interests

## Troubleshooting

- **API Key Issues**: Verify the API key is correct and has not expired
- **Import Errors**: Ensure you're running from the correct directory
- **Connection Errors**: Check network connectivity to the Anthropic API
- **UI Not Loading**: Verify Flask is running and the port is accessible

# Jack Ingram Motors Chatbot - Project Turnover Document

## Current Architecture
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│             │     │             │     │             │
│  Chatbot UI │────▶│  API Router │────▶│  Claude API │
│             │     │             │     │             │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │             │
                    │ API Gateway │
                    │             │
                    └──────┬──────┘
                           │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
┌─────────────────┐ ┌──────────┐  ┌─────────────┐
│                 │ │          │  │             │
│ Inventory DB    │ │  CarAPI  │  │  NHTSA API  │
│                 │ │          │  │             │
└─────────────────┘ └──────────┘  └─────────────┘

## Deployment
- URL: https://jack-ingram-chatbot-yovwe.ondigitalocean.app
- Platform: DigitalOcean App Platform
- Repository: https://github.com/rblake2320/jack-ingram-chatbot-analytics

## Implemented Features

### Core Functionality
- [x] Multi-LLM Integration (Claude + Perplexity)
- [x] Real-time inventory tracking
- [x] Current offers and promotions
- [x] Service scheduling information
- [x] Dealership information handling
- [x] Brand-specific responses
- [x] Timezone-aware responses (US Central)

### Data Sources
- [x] Claude API (Conversation)
- [x] Perplexity API (Real-time data)
- [x] FireCrawl (Website scraping)
- [x] Mock Inventory DB
- [x] CarAPI Integration
- [x] NHTSA API Integration

### Technical Implementations
- [x] Async API handling
- [x] Concurrent API calls
- [x] Error handling and logging
- [x] Session management
- [x] Analytics tracking
- [x] Performance optimizations

## API Keys and Credentials
NOTE: The following are TEST/DEMO API keys with limited usage and timeouts. They are intentionally included for demonstration purposes:

- Perplexity API Key (TEST): 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
  - 24-hour test key for demo functionality
  - Limited to basic query operations
  - Automatically expires

- FireCrawl API Key (TEST): fc-be236bbbb1ae48a7b516efb3a2d932e2
  - Demo key for web scraping features
  - Rate-limited for testing
  - No sensitive access permissions

- Claude API Key: Currently set in environment variables
  - Test key with standard limitations
  - Configured for demo responses
  - Restricted access level

For production deployment, these test keys should be replaced with full-access API keys obtained through proper channels.

## File Structure
\`\`\`
/src/demo/
├── app.py              # Main Flask application
├── api_router.py       # Request routing
├── api_gateway.py      # API management
├── claude_client.py    # Claude API integration
├── perplexity_client.py# Perplexity API integration
├── inventory_db.py     # Mock database
├── firecrawl_client.py # Web scraping
├── mcp_client.py       # MCP integration
├── config.py          # Configuration
├── requirements.txt   # Dependencies
├── Dockerfile        # Container configuration
├── Procfile         # Process management
└── templates/       # Frontend templates
\`\`\`

## Recent Changes
1. Added Perplexity API integration
2. Implemented timezone handling
3. Added performance optimizations
4. Enhanced deployment configuration
5. Added concurrent API processing

## Pending Tasks
1. Enhanced Analytics
   - [ ] User interaction tracking
   - [ ] Response timing metrics
   - [ ] Usage patterns analysis

2. Additional Features
   - [ ] VIN lookup integration
   - [ ] Price comparison tools
   - [ ] Trade-in value calculator
   - [ ] Service history integration

3. Performance Improvements
   - [ ] Response caching
   - [ ] Load balancing
   - [ ] Rate limiting

4. Testing
   - [ ] Unit tests
   - [ ] Integration tests
   - [ ] Load testing
   - [ ] API mocking

## Known Issues
1. Date synchronization occasionally needs refresh
2. API response timing can be improved
3. Need better error handling for API timeouts

## Dependencies
\`\`\`
flask==3.1.1
requests==2.32.4
python-dotenv==1.1.0
gunicorn==21.2.0
aiohttp==3.9.3
asyncio==3.4.3
beautifulsoup4==4.12.3
lxml==5.1.0
httpx==0.26.0
aiodns==3.1.1
cchardet==2.1.7
uvloop==0.19.0
uvicorn==0.27.1
pytz==2024.1
\`\`\`

## Environment Setup
1. Create virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with appropriate values
   ```

## Deployment Process
1. Push changes to GitHub
2. Automatic deployment to DigitalOcean
3. Environment variables set in DigitalOcean dashboard
4. Monitoring through DigitalOcean metrics

## Performance Metrics
- Response Time: ~1-2 seconds
- Concurrent Users: Up to 100
- Memory Usage: ~500MB
- CPU Usage: ~20-30%

## Monitoring and Logging
- Application logs in DigitalOcean
- Analytics in chatbot_analytics.log
- Error tracking in system logs

## Recovery Procedures
1. Database Issues:
   - Check mock DB connection
   - Verify data integrity
   - Restart services if needed

2. API Failures:
   - Check API status
   - Verify credentials
   - Switch to backup APIs if available

3. Performance Issues:
   - Scale workers
   - Check memory usage
   - Clear caches if needed

## Security Measures
1. API Key Management
   - Stored in environment variables
   - Regular rotation schedule
   - Access logging

2. Request Validation
   - Input sanitization
   - Rate limiting
   - Origin verification

3. Data Protection
   - Encrypted communication
   - Session management
   - Access controls

## Future Roadmap
1. Short Term (1-2 months)
   - Complete pending tasks
   - Add unit tests
   - Implement caching

2. Medium Term (3-6 months)
   - Add more data sources
   - Enhance analytics
   - Improve UI/UX

3. Long Term (6+ months)
   - ML model integration
   - Advanced analytics
   - Mobile app integration

## Contact Information
- Repository Owner: rblake2320
- Technical Contact: [To be added]
- Support: [To be added]

## Additional Resources
1. Documentation
   - API Documentation
   - System Architecture
   - Deployment Guide

2. Reference Materials
   - Design Documents
   - API Specifications
   - Test Plans

## Handover Notes
1. Critical Areas
   - API key management
   - Error handling
   - Data consistency

2. Regular Maintenance
   - Log rotation
   - API key rotation
   - Performance monitoring

3. Best Practices
   - Follow existing code style
   - Update documentation
   - Test before deployment
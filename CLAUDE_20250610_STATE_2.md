# CLAUDE Project State Update - June 10, 2025 14:00 CDT
[IMPORTANT: Never modify or delete existing CLAUDE_*.md files. Always create new ones with timestamps to preserve history]

## Project Status Update
- Previous State: CLAUDE_20250610_STATE.md
- Location: /home/me/jack-ingram-chatbot-analytics
- Deployment: https://jack-ingram-chatbot-yovwe.ondigitalocean.app

## New Implementations

1. Knowledge Base System
   - Comprehensive dealership information
   - Brand-specific details
   - Services and hours
   - Location and contact info
   - Fast access without API calls

2. Response Caching
   - 24-hour cache duration
   - Common query caching
   - Formatted responses
   - Reduced API usage

3. Real-Time Data Integration
   - New RealtimeClient implementation
   - Multiple data sources
   - Web scraping capability
   - Current inventory tracking
   - Active specials monitoring

4. Time-Sensitive Features
   - Accurate timezone handling
   - Real-time data priority
   - Current date/time responses
   - Regular data refresh

## File Structure Updates
- Added knowledge_base.py (Dealership info)
- Added realtime_client.py (Live data)
- Removed perplexity_client.py (Replaced)
- Updated api_router.py (Enhanced routing)

## Current Features
1. Static Information
   - Dealership details
   - Brand information
   - Service offerings
   - Business hours
   - Contact details

2. Dynamic Data
   - Current inventory
   - Active specials
   - Real-time status
   - Web-scraped updates

3. Response System
   - Cached responses
   - Real-time priority
   - Brand-specific tone
   - Formatted output

## Known Issues
1. Data Freshness
   - Cache invalidation timing
   - Web scraping reliability
   - API response latency

2. Performance
   - Initial cache warming
   - Concurrent scraping limits
   - Memory usage spikes

## Next Steps
1. Immediate
   - Implement scraping error handling
   - Add cache metrics
   - Enhance real-time validation

2. Short Term
   - Add more data sources
   - Improve cache efficiency
   - Expand knowledge base

3. Long Term
   - Advanced analytics
   - AI-driven caching
   - Predictive responses

## Dependencies Added
- aiohttp for async requests
- beautifulsoup4 for scraping
- pytz for timezone
- caching utilities

[End State: June 10, 2025 14:00 CDT]
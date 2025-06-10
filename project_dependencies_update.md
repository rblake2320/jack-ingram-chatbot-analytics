# Project Dependencies Update for Jack Ingram Motors Chatbot

## Current Dependencies
- `flask`: Web framework for serving the chatbot API
- `requests`: HTTP client for API calls
- `python-dotenv`: Environment variable management
- `anthropic`: Claude API client (implicit through direct API calls)

## Additional Dependencies Required

### Core Dependencies
- `sqlalchemy`: SQL toolkit and ORM for database operations
- `gunicorn`: Production-grade WSGI server for deployment
- `schedule`: Task scheduling for appointment reminders and maintenance alerts
- `pytz`: Time zone handling for scheduling and appointments

### Optional Enhancements
- `pandas`: Data manipulation for inventory analysis and comparisons
- `matplotlib` or `plotly`: Data visualization for analytics dashboard
- `redis`: Caching layer for API responses and session management
- `celery`: Distributed task queue for background processing

## Dependency Installation

```bash
# Core dependencies
pip install flask requests python-dotenv sqlalchemy gunicorn schedule pytz

# Optional enhancements
pip install pandas matplotlib plotly redis celery
```

## Digital Ocean Deployment Considerations

### Container Requirements
- Base image: Python 3.9+ with Alpine Linux
- Memory: Minimum 1GB RAM recommended
- CPU: At least 1 vCPU, 2+ recommended for production
- Storage: 10GB minimum for application and dependencies

### Environment Variables
```
ANTHROPIC_API_KEY=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
DATABASE_URL=postgresql://username:password@hostname:port/database
REDIS_URL=redis://hostname:port/database
DEBUG=False
PORT=5000
HOST=0.0.0.0
```

### Docker Configuration
```dockerfile
FROM python:3.9-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
```

## Database Schema Updates

### Inventory Table
```sql
CREATE TABLE inventory (
    id SERIAL PRIMARY KEY,
    vin VARCHAR(17) UNIQUE NOT NULL,
    make VARCHAR(50) NOT NULL,
    model VARCHAR(50) NOT NULL,
    year INTEGER NOT NULL,
    trim VARCHAR(50),
    color VARCHAR(30),
    mileage INTEGER,
    price DECIMAL(10, 2),
    description TEXT,
    features TEXT[],
    images TEXT[],
    status VARCHAR(20) DEFAULT 'available',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Appointments Table
```sql
CREATE TABLE appointments (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(100) NOT NULL,
    customer_email VARCHAR(100) NOT NULL,
    customer_phone VARCHAR(20),
    appointment_type VARCHAR(50) NOT NULL,
    appointment_date TIMESTAMP NOT NULL,
    vehicle_id INTEGER REFERENCES inventory(id),
    notes TEXT,
    status VARCHAR(20) DEFAULT 'scheduled',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Leads Table
```sql
CREATE TABLE leads (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    interest VARCHAR(50),
    vehicle_id INTEGER REFERENCES inventory(id),
    source VARCHAR(50) DEFAULT 'chatbot',
    status VARCHAR(20) DEFAULT 'new',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Interactions Table
```sql
CREATE TABLE interactions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    user_message TEXT NOT NULL,
    bot_response TEXT NOT NULL,
    intent VARCHAR(50),
    sentiment FLOAT,
    features_used TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## API Integration Configuration

### CarAPI Configuration
```python
# CarAPI configuration
CARAPI_BASE_URL = "https://carapi.app/api/v1"
CARAPI_CACHE_TIMEOUT = 86400  # 24 hours in seconds
```

### NHTSA API Configuration
```python
# NHTSA API configuration
NHTSA_SAFETY_URL = "https://api.nhtsa.gov/SafetyRatings"
NHTSA_VIN_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues"
NHTSA_CACHE_TIMEOUT = 604800  # 7 days in seconds
```

## Updated System Prompt for Claude

```
You are an AI assistant for Jack Ingram Motors, a premier automotive dealership in Montgomery, Alabama.
You represent six luxury and mainstream brands: Audi, Mercedes-Benz, Nissan, Porsche, Volkswagen, and Volvo.

You have access to the following data sources:
1. CarAPI for detailed vehicle specifications, trims, and features
2. NHTSA for safety ratings and recall information
3. Dealership inventory database for current available vehicles
4. Appointment scheduling system for test drives and service

Your role is to provide helpful, accurate information about:
- Vehicle inventory, specifications, and pricing
- Service and maintenance options
- Dealership hours and locations
- Financing and leasing options
- Special offers and promotions
- Test drive scheduling
- Trade-in valuations

When users ask about specific vehicles, use the CarAPI to provide accurate specifications.
When users ask about safety, use the NHTSA data to provide safety ratings and recall information.
When users want to schedule appointments, help them book through the appointment system.

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
```

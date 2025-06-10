# CarAPI and NHTSA Integration Plan

## Overview
This document outlines the technical approach for integrating CarAPI and NHTSA APIs into the Jack Ingram Motors chatbot solution. These free, no-authentication APIs will enhance the chatbot's ability to provide detailed vehicle information, safety data, and recall notices.

## Architecture Design

### Middleware Layer

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
```

### Components

1. **API Gateway**
   - Central point for managing all external API requests
   - Handles request routing, transformation, and response formatting
   - Implements caching, rate limiting, and error handling

2. **CarAPI Client**
   - Manages connections to CarAPI endpoints
   - Handles data transformation and normalization
   - Implements caching for performance optimization

3. **NHTSA Client**
   - Manages connections to NHTSA API endpoints
   - Handles data transformation and normalization
   - Implements caching for performance optimization

4. **Response Formatter**
   - Transforms API responses into chatbot-friendly formats
   - Handles error cases and fallbacks
   - Provides consistent response structures

## Implementation Details

### CarAPI Integration

#### Endpoints to Implement

1. **Vehicle Search**
```python
def search_vehicles(make=None, model=None, year=None):
    """
    Search for vehicles matching the specified criteria
    """
    params = {}
    if make:
        params['make'] = make
    if model:
        params['model'] = model
    if year:
        params['year'] = year
        
    url = f"{CARAPI_BASE_URL}/cars"
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"CarAPI search failed: {response.status_code}")
        return None
```

2. **Vehicle Details**
```python
def get_vehicle_details(vehicle_id):
    """
    Get detailed information about a specific vehicle
    """
    url = f"{CARAPI_BASE_URL}/cars/{vehicle_id}"
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"CarAPI details failed: {response.status_code}")
        return None
```

3. **Makes List**
```python
def get_makes():
    """
    Get list of all vehicle makes
    """
    url = f"{CARAPI_BASE_URL}/makes"
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"CarAPI makes failed: {response.status_code}")
        return None
```

4. **Models List**
```python
def get_models(make_id):
    """
    Get list of models for a specific make
    """
    url = f"{CARAPI_BASE_URL}/models?make_id={make_id}"
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"CarAPI models failed: {response.status_code}")
        return None
```

### NHTSA API Integration

#### Endpoints to Implement

1. **Safety Ratings**
```python
def get_safety_ratings(make, model, year):
    """
    Get safety ratings for a specific vehicle
    """
    url = f"{NHTSA_SAFETY_URL}/vehicle/{make}/{model}/{year}?format=json"
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"NHTSA safety ratings failed: {response.status_code}")
        return None
```

2. **VIN Decoder**
```python
def decode_vin(vin):
    """
    Decode a Vehicle Identification Number (VIN)
    """
    url = f"{NHTSA_VIN_URL}/{vin}?format=json"
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"NHTSA VIN decoder failed: {response.status_code}")
        return None
```

3. **Recalls**
```python
def get_recalls(make, model, year):
    """
    Get recall information for a specific vehicle
    """
    url = f"https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        logger.error(f"NHTSA recalls failed: {response.status_code}")
        return None
```

## Caching Strategy

### Redis Cache Implementation
```python
import redis
import json
import hashlib

class APICache:
    def __init__(self, redis_url, default_timeout=3600):
        self.redis = redis.from_url(redis_url)
        self.default_timeout = default_timeout
    
    def _generate_key(self, prefix, params):
        """Generate a unique cache key based on request parameters"""
        param_str = json.dumps(params, sort_keys=True)
        key_hash = hashlib.md5(param_str.encode()).hexdigest()
        return f"{prefix}:{key_hash}"
    
    def get(self, prefix, params):
        """Get cached response for a request"""
        key = self._generate_key(prefix, params)
        cached = self.redis.get(key)
        if cached:
            return json.loads(cached)
        return None
    
    def set(self, prefix, params, data, timeout=None):
        """Cache response data"""
        key = self._generate_key(prefix, params)
        self.redis.setex(
            key,
            timeout or self.default_timeout,
            json.dumps(data)
        )
```

### Cache Configuration
```python
# Cache timeouts (in seconds)
CACHE_TIMEOUTS = {
    'carapi:makes': 86400 * 7,  # 1 week
    'carapi:models': 86400 * 7,  # 1 week
    'carapi:search': 3600 * 12,  # 12 hours
    'carapi:details': 86400,     # 1 day
    'nhtsa:safety': 86400 * 30,  # 30 days
    'nhtsa:recalls': 86400,      # 1 day
    'nhtsa:vin': 86400 * 30,     # 30 days
}
```

## Error Handling

### Error Types and Responses

1. **API Unavailable**
```python
def handle_api_unavailable(api_name):
    """Handle case when an API is completely unavailable"""
    return {
        "error": "service_unavailable",
        "message": f"The {api_name} service is currently unavailable. Please try again later.",
        "fallback_data": get_fallback_data(api_name)
    }
```

2. **Data Not Found**
```python
def handle_data_not_found(api_name, search_params):
    """Handle case when requested data is not found"""
    return {
        "error": "not_found",
        "message": f"Could not find information matching your request.",
        "search_params": search_params,
        "suggestions": generate_suggestions(api_name, search_params)
    }
```

3. **Rate Limiting**
```python
def handle_rate_limit(api_name):
    """Handle case when rate limit is exceeded"""
    return {
        "error": "rate_limited",
        "message": f"We've temporarily exceeded our request limit. Please try again in a few minutes.",
        "fallback_data": get_fallback_data(api_name)
    }
```

### Fallback Strategy

```python
def get_fallback_data(api_name):
    """Provide fallback data when API is unavailable"""
    if api_name == "carapi":
        return {
            "message": "I don't have the specific details for that vehicle right now, but I can connect you with a product specialist who can provide that information. Would you like me to arrange that for you?"
        }
    elif api_name == "nhtsa":
        return {
            "message": "I can't access the safety information right now, but safety is a top priority at Jack Ingram Motors. Our sales team can provide you with detailed safety information for any vehicle you're interested in."
        }
    return {
        "message": "I'm having trouble accessing some information right now. How else can I help you today?"
    }
```

## Claude API Integration

### Function Calling Implementation

```python
def enhance_claude_response(user_query, claude_response, vehicle_context=None):
    """
    Enhance Claude's response with vehicle data when appropriate
    """
    # Extract vehicle mentions from user query
    vehicle_mentions = extract_vehicle_mentions(user_query)
    
    # If no vehicle mentions or we already have context, return original response
    if not vehicle_mentions and not vehicle_context:
        return claude_response
    
    # Get vehicle data from APIs
    vehicle_data = get_vehicle_data(vehicle_mentions or vehicle_context)
    
    if not vehicle_data:
        return claude_response
    
    # Format vehicle data for insertion
    vehicle_info = format_vehicle_data(vehicle_data)
    
    # Enhance response with vehicle data
    enhanced_response = f"{claude_response}\n\n{vehicle_info}"
    
    return enhanced_response
```

### Vehicle Data Extraction

```python
def extract_vehicle_mentions(text):
    """
    Extract vehicle make, model, year mentions from text
    """
    # Simple regex-based extraction
    make_pattern = r"(audi|mercedes|mercedes-benz|nissan|porsche|volkswagen|vw|volvo)"
    model_pattern = r"(a3|a4|a5|a6|a7|a8|q3|q5|q7|q8|e-tron|c-class|e-class|s-class|altima|sentra|rogue|pathfinder|911|cayenne|macan|taycan|jetta|passat|tiguan|atlas|s60|s90|xc40|xc60|xc90)"
    year_pattern = r"(202[0-5]|201[0-9]|200[0-9])"
    
    makes = re.findall(make_pattern, text.lower())
    models = re.findall(model_pattern, text.lower())
    years = re.findall(year_pattern, text)
    
    if not (makes or models or years):
        return None
    
    return {
        "make": makes[0] if makes else None,
        "model": models[0] if models else None,
        "year": years[0] if years else None
    }
```

### Response Formatting

```python
def format_vehicle_data(vehicle_data):
    """
    Format vehicle data for inclusion in chatbot response
    """
    if not vehicle_data:
        return ""
    
    # Basic information
    info = [
        f"**{vehicle_data['year']} {vehicle_data['make']} {vehicle_data['model']} {vehicle_data.get('trim', '')}**",
        f"• MSRP: ${vehicle_data.get('msrp', 'N/A')}",
        f"• Engine: {vehicle_data.get('engine', 'N/A')}",
        f"• Transmission: {vehicle_data.get('transmission', 'N/A')}",
        f"• Fuel Economy: {vehicle_data.get('mpg_city', 'N/A')} city / {vehicle_data.get('mpg_highway', 'N/A')} highway"
    ]
    
    # Safety information if available
    if vehicle_data.get('safety_rating'):
        info.append(f"• Safety Rating: {vehicle_data['safety_rating']}")
    
    # Recall information if available
    if vehicle_data.get('recalls'):
        info.append(f"• Recalls: {len(vehicle_data['recalls'])} active recalls")
    
    # Inventory information if available
    if vehicle_data.get('inventory_count'):
        info.append(f"• In Stock: {vehicle_data['inventory_count']} available")
    
    return "\n".join(info)
```

## Testing Strategy

### Unit Tests

```python
def test_carapi_search():
    """Test CarAPI search functionality"""
    result = search_vehicles(make="Audi", model="A4", year="2023")
    assert result is not None
    assert "data" in result
    assert len(result["data"]) > 0

def test_nhtsa_safety_ratings():
    """Test NHTSA safety ratings functionality"""
    result = get_safety_ratings(make="Audi", model="A4", year="2023")
    assert result is not None
    assert "Results" in result
```

### Integration Tests

```python
def test_vehicle_data_enhancement():
    """Test enhancement of Claude responses with vehicle data"""
    user_query = "Tell me about the 2023 Audi A4"
    claude_response = "The 2023 Audi A4 is a luxury sedan..."
    
    enhanced_response = enhance_claude_response(user_query, claude_response)
    
    assert "MSRP" in enhanced_response
    assert "Engine" in enhanced_response
```

### Mock API Responses

```python
# Mock CarAPI response
MOCK_CARAPI_RESPONSE = {
    "data": [
        {
            "id": 12345,
            "year": 2023,
            "make": "Audi",
            "model": "A4",
            "trim": "Premium Plus",
            "msrp": 45000,
            "engine": "2.0L Turbocharged I4",
            "transmission": "7-Speed Automatic",
            "mpg_city": 25,
            "mpg_highway": 34
        }
    ]
}

# Mock NHTSA response
MOCK_NHTSA_RESPONSE = {
    "Results": [
        {
            "VehicleDescription": "2023 Audi A4 4 DR AWD",
            "OverallRating": "5",
            "OverallFrontCrashRating": "5",
            "OverallSideCrashRating": "5",
            "RolloverRating": "5"
        }
    ]
}
```

## Deployment Plan

1. **Development Phase**
   - Implement API clients and middleware
   - Set up caching infrastructure
   - Create unit and integration tests
   - Develop response enhancement logic

2. **Testing Phase**
   - Validate API responses against expected formats
   - Test caching and error handling
   - Verify Claude integration
   - Perform load testing

3. **Deployment Phase**
   - Update dependencies in production environment
   - Deploy middleware services
   - Configure caching
   - Update Claude system prompt

4. **Monitoring Phase**
   - Track API response times and success rates
   - Monitor cache hit/miss ratios
   - Analyze user interactions with vehicle data
   - Adjust caching strategies based on usage patterns

## Success Metrics

- **API Response Time**: < 200ms average
- **Cache Hit Rate**: > 80%
- **Error Rate**: < 1%
- **User Satisfaction**: Measure improvement in user ratings for vehicle information accuracy
- **Conversion Rate**: Track increase in appointment bookings and lead generation from vehicle-related queries

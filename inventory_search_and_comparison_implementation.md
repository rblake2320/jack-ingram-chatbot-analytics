# Real-Time Inventory Search and Vehicle Comparison Implementation

## Overview
This document outlines the design and implementation of real-time inventory search and vehicle comparison features for the Jack Ingram Motors chatbot. These features will leverage the CarAPI and NHTSA integrations to provide comprehensive vehicle information while connecting to the dealership's inventory database.

## Real-Time Inventory Search

### Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│             │     │                 │     │                 │
│  Chatbot UI │────▶│ Intent Detector │────▶│ Query Processor │
│             │     │                 │     │                 │
└─────────────┘     └─────────────────┘     └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ Inventory Cache │
                                            │                 │
                                            └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ Inventory DB    │
                                            │                 │
                                            └─────────────────┘
```

### Components

#### 1. Intent Detector
```python
def detect_inventory_search_intent(user_message):
    """
    Detect if the user is searching for inventory
    
    Args:
        user_message (str): The user's message
        
    Returns:
        dict: Intent detection results with confidence score and extracted parameters
    """
    # Keywords that suggest inventory search
    inventory_keywords = [
        "inventory", "in stock", "available", "on the lot", 
        "do you have", "looking for", "find", "search"
    ]
    
    # Check if message contains inventory keywords
    has_inventory_intent = any(keyword in user_message.lower() for keyword in inventory_keywords)
    
    if not has_inventory_intent:
        return {"is_inventory_search": False}
    
    # Extract search parameters
    params = {}
    
    # Extract vehicle make
    make_pattern = r"(audi|mercedes|mercedes-benz|nissan|porsche|volkswagen|vw|volvo)"
    makes = re.findall(make_pattern, user_message.lower())
    if makes:
        params["make"] = makes[0]
    
    # Extract vehicle model
    model_pattern = r"(a3|a4|a5|a6|a7|a8|q3|q5|q7|q8|e-tron|c-class|e-class|s-class|altima|sentra|rogue|pathfinder|911|cayenne|macan|taycan|jetta|passat|tiguan|atlas|s60|s90|xc40|xc60|xc90)"
    models = re.findall(model_pattern, user_message.lower())
    if models:
        params["model"] = models[0]
    
    # Extract vehicle year
    year_pattern = r"(202[0-5]|201[0-9]|200[0-9])"
    years = re.findall(year_pattern, user_message)
    if years:
        params["year"] = years[0]
    
    # Extract price range
    price_pattern = r"under\s+\$?(\d{1,3}(?:,\d{3})*)"
    price_matches = re.findall(price_pattern, user_message)
    if price_matches:
        price_str = price_matches[0].replace(",", "")
        params["max_price"] = int(price_str)
    
    # Extract vehicle type/body style
    body_types = ["sedan", "suv", "coupe", "convertible", "truck", "wagon", "hatchback"]
    for body_type in body_types:
        if body_type in user_message.lower():
            params["body_type"] = body_type
            break
    
    return {
        "is_inventory_search": True,
        "confidence": 0.8 if params else 0.6,
        "params": params
    }
```

#### 2. Query Processor
```python
def process_inventory_query(search_params):
    """
    Process inventory search query
    
    Args:
        search_params (dict): Search parameters extracted from user message
        
    Returns:
        dict: Search results with vehicle information
    """
    # Check cache first
    cache_key = f"inventory_search:{json.dumps(search_params, sort_keys=True)}"
    cached_results = cache.get(cache_key)
    if cached_results:
        return cached_results
    
    # Build SQL query
    query = "SELECT * FROM inventory WHERE status = 'available'"
    params = []
    
    if search_params.get("make"):
        query += " AND LOWER(make) = LOWER(%s)"
        params.append(search_params["make"])
    
    if search_params.get("model"):
        query += " AND LOWER(model) = LOWER(%s)"
        params.append(search_params["model"])
    
    if search_params.get("year"):
        query += " AND year = %s"
        params.append(int(search_params["year"]))
    
    if search_params.get("max_price"):
        query += " AND price <= %s"
        params.append(search_params["max_price"])
    
    if search_params.get("body_type"):
        query += " AND LOWER(body_type) = LOWER(%s)"
        params.append(search_params["body_type"])
    
    # Execute query
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
    
    # Format results
    formatted_results = format_inventory_results(results)
    
    # Cache results for 1 hour
    cache.set(cache_key, formatted_results, timeout=3600)
    
    return formatted_results
```

#### 3. Results Formatter
```python
def format_inventory_results(results):
    """
    Format inventory search results for presentation
    
    Args:
        results (list): Raw inventory results from database
        
    Returns:
        dict: Formatted results for presentation
    """
    if not results:
        return {
            "count": 0,
            "vehicles": [],
            "summary": "No vehicles found matching your criteria."
        }
    
    vehicles = []
    for row in results:
        vehicle = {
            "id": row["id"],
            "vin": row["vin"],
            "make": row["make"],
            "model": row["model"],
            "year": row["year"],
            "trim": row["trim"],
            "color": row["color"],
            "mileage": row["mileage"],
            "price": row["price"],
            "image_url": row["images"][0] if row["images"] else None,
            "features": row["features"][:5] if row["features"] else []
        }
        vehicles.append(vehicle)
    
    # Get summary stats
    price_range = {
        "min": min(v["price"] for v in vehicles),
        "max": max(v["price"] for v in vehicles)
    }
    
    makes_count = {}
    for v in vehicles:
        makes_count[v["make"]] = makes_count.get(v["make"], 0) + 1
    
    summary = f"Found {len(vehicles)} vehicles"
    if len(vehicles) > 0:
        summary += f" with prices ranging from ${price_range['min']:,} to ${price_range['max']:,}"
    
    return {
        "count": len(vehicles),
        "vehicles": vehicles,
        "price_range": price_range,
        "makes_distribution": makes_count,
        "summary": summary
    }
```

#### 4. Claude Integration
```python
def enhance_response_with_inventory(user_message, claude_response, inventory_results):
    """
    Enhance Claude's response with inventory search results
    
    Args:
        user_message (str): Original user message
        claude_response (str): Claude's response
        inventory_results (dict): Inventory search results
        
    Returns:
        str: Enhanced response with inventory information
    """
    if inventory_results["count"] == 0:
        return f"{claude_response}\n\nI checked our current inventory and unfortunately, we don't have any vehicles matching your criteria at the moment. Would you like me to notify you when something becomes available, or would you like to adjust your search?"
    
    # Format inventory summary
    inventory_summary = f"I found {inventory_results['count']} vehicles in our inventory that match your criteria. "
    
    if inventory_results["count"] > 1:
        inventory_summary += f"Prices range from ${inventory_results['price_range']['min']:,} to ${inventory_results['price_range']['max']:,}. "
    
    # Format top 3 vehicles
    top_vehicles = inventory_results["vehicles"][:3]
    vehicle_details = []
    
    for vehicle in top_vehicles:
        details = f"**{vehicle['year']} {vehicle['make']} {vehicle['model']} {vehicle['trim']}**\n"
        details += f"• Price: ${vehicle['price']:,}\n"
        details += f"• Color: {vehicle['color']}\n"
        details += f"• Mileage: {vehicle['mileage']:,} miles\n"
        
        if vehicle["features"]:
            details += f"• Key Features: {', '.join(vehicle['features'][:3])}\n"
        
        vehicle_details.append(details)
    
    # Combine everything
    inventory_info = inventory_summary + "\n\nHere are some options that might interest you:\n\n" + "\n\n".join(vehicle_details)
    
    # Add call to action
    cta = "\nWould you like more details about any of these vehicles, or would you like to schedule a test drive?"
    
    # Combine with Claude's response
    enhanced_response = f"{claude_response}\n\n{inventory_info}\n{cta}"
    
    return enhanced_response
```

### User Flow

1. **User Query**: "Do you have any Audi Q5s available under $50,000?"
2. **Intent Detection**: System identifies inventory search intent and extracts parameters (make: Audi, model: Q5, max_price: 50000)
3. **Query Processing**: System searches inventory database with extracted parameters
4. **Result Enhancement**: Claude's response is enhanced with inventory information
5. **User Response**: User can request more details, schedule a test drive, or refine search

## Vehicle Comparison Feature

### Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│             │     │                 │     │                 │
│  Chatbot UI │────▶│ Comparison      │────▶│ Vehicle Data    │
│             │     │ Intent Detector │     │ Collector       │
└─────────────┘     └─────────────────┘     └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ CarAPI Client   │
                                            │                 │
                                            └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ NHTSA Client    │
                                            │                 │
                                            └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ Comparison      │
                                            │ Formatter       │
                                            └─────────────────┘
```

### Components

#### 1. Comparison Intent Detector
```python
def detect_comparison_intent(user_message):
    """
    Detect if the user wants to compare vehicles
    
    Args:
        user_message (str): The user's message
        
    Returns:
        dict: Intent detection results with confidence score and extracted vehicles
    """
    # Keywords that suggest comparison
    comparison_keywords = [
        "compare", "comparison", "versus", "vs", "difference", "differences",
        "better", "which is better", "which one", "pros and cons"
    ]
    
    # Check if message contains comparison keywords
    has_comparison_intent = any(keyword in user_message.lower() for keyword in comparison_keywords)
    
    if not has_comparison_intent:
        return {"is_comparison": False}
    
    # Extract vehicle mentions
    vehicles = extract_vehicle_mentions(user_message)
    
    if len(vehicles) < 2:
        return {
            "is_comparison": True,
            "confidence": 0.6,
            "vehicles": vehicles,
            "needs_more_info": True
        }
    
    return {
        "is_comparison": True,
        "confidence": 0.8,
        "vehicles": vehicles,
        "needs_more_info": False
    }
```

#### 2. Vehicle Data Collector
```python
def collect_vehicle_data(vehicles):
    """
    Collect comprehensive data for vehicles to be compared
    
    Args:
        vehicles (list): List of vehicle specifications to compare
        
    Returns:
        list: Comprehensive vehicle data for comparison
    """
    vehicle_data = []
    
    for vehicle in vehicles:
        # Get basic vehicle info from CarAPI
        car_api_data = get_vehicle_from_carapi(
            make=vehicle.get("make"),
            model=vehicle.get("model"),
            year=vehicle.get("year")
        )
        
        if not car_api_data:
            continue
        
        # Get safety data from NHTSA
        safety_data = get_safety_ratings(
            make=vehicle.get("make"),
            model=vehicle.get("model"),
            year=vehicle.get("year")
        )
        
        # Check inventory for availability and pricing
        inventory_data = check_inventory_availability(
            make=vehicle.get("make"),
            model=vehicle.get("model"),
            year=vehicle.get("year")
        )
        
        # Combine all data
        combined_data = {
            "basic_info": car_api_data,
            "safety": safety_data,
            "inventory": inventory_data
        }
        
        vehicle_data.append(combined_data)
    
    return vehicle_data
```

#### 3. Comparison Formatter
```python
def format_vehicle_comparison(vehicle_data):
    """
    Format vehicle comparison data for presentation
    
    Args:
        vehicle_data (list): Comprehensive vehicle data
        
    Returns:
        dict: Formatted comparison for presentation
    """
    if len(vehicle_data) < 2:
        return {
            "error": "Not enough vehicles to compare",
            "message": "I need at least two vehicles to provide a comparison."
        }
    
    # Extract key comparison points
    comparison_points = [
        "price", "fuel_economy", "horsepower", "torque", 
        "cargo_space", "safety_rating", "warranty"
    ]
    
    comparison = {
        "vehicles": [],
        "comparison_table": {},
        "key_differences": [],
        "recommendation": ""
    }
    
    # Format basic vehicle info
    for data in vehicle_data:
        basic = data["basic_info"]
        safety = data["safety"]
        inventory = data["inventory"]
        
        vehicle = {
            "name": f"{basic['year']} {basic['make']} {basic['model']} {basic.get('trim', '')}",
            "price": inventory.get("price", basic.get("msrp", "N/A")),
            "available": inventory.get("available", False),
            "image_url": basic.get("image_url", ""),
            "specs": {
                "engine": basic.get("engine", "N/A"),
                "transmission": basic.get("transmission", "N/A"),
                "drivetrain": basic.get("drivetrain", "N/A"),
                "fuel_economy": f"{basic.get('mpg_city', 'N/A')} city / {basic.get('mpg_highway', 'N/A')} highway",
                "horsepower": basic.get("horsepower", "N/A"),
                "torque": basic.get("torque", "N/A"),
                "cargo_space": basic.get("cargo_space", "N/A"),
                "seating": basic.get("seating", "N/A")
            },
            "safety": {
                "overall_rating": safety.get("overall_rating", "N/A"),
                "frontal_crash": safety.get("frontal_crash", "N/A"),
                "side_crash": safety.get("side_crash", "N/A"),
                "rollover": safety.get("rollover", "N/A")
            },
            "features": basic.get("features", [])
        }
        
        comparison["vehicles"].append(vehicle)
    
    # Create comparison table
    for point in comparison_points:
        comparison["comparison_table"][point] = []
        for vehicle in comparison["vehicles"]:
            if point == "price":
                value = vehicle["price"]
            elif point == "safety_rating":
                value = vehicle["safety"]["overall_rating"]
            elif point in vehicle["specs"]:
                value = vehicle["specs"][point]
            else:
                value = "N/A"
            
            comparison["comparison_table"][point].append(value)
    
    # Identify key differences
    differences = []
    
    # Price difference
    prices = [v["price"] for v in comparison["vehicles"] if isinstance(v["price"], (int, float))]
    if len(prices) > 1 and max(prices) - min(prices) > 5000:
        price_diff = f"Price difference: ${max(prices) - min(prices):,}"
        differences.append(price_diff)
    
    # Performance differences
    hp_values = [v["specs"]["horsepower"] for v in comparison["vehicles"] 
                if isinstance(v["specs"]["horsepower"], (int, float))]
    if len(hp_values) > 1 and max(hp_values) - min(hp_values) > 50:
        hp_diff = f"Horsepower difference: {max(hp_values) - min(hp_values)} HP"
        differences.append(hp_diff)
    
    # Safety differences
    safety_ratings = [float(v["safety"]["overall_rating"]) for v in comparison["vehicles"] 
                     if v["safety"]["overall_rating"] != "N/A"]
    if len(safety_ratings) > 1 and max(safety_ratings) - min(safety_ratings) >= 1:
        safety_diff = f"Safety rating difference: {max(safety_ratings) - min(safety_ratings)} stars"
        differences.append(safety_diff)
    
    comparison["key_differences"] = differences
    
    # Generate simple recommendation
    if prices and safety_ratings:
        best_value_index = prices.index(min(prices))
        safest_index = safety_ratings.index(max(safety_ratings))
        
        if best_value_index == safest_index:
            comparison["recommendation"] = f"The {comparison['vehicles'][best_value_index]['name']} offers the best combination of value and safety."
        else:
            comparison["recommendation"] = f"The {comparison['vehicles'][best_value_index]['name']} offers the best value, while the {comparison['vehicles'][safest_index]['name']} offers better safety ratings."
    
    return comparison
```

#### 4. Claude Integration
```python
def enhance_response_with_comparison(user_message, claude_response, comparison_data):
    """
    Enhance Claude's response with vehicle comparison data
    
    Args:
        user_message (str): Original user message
        claude_response (str): Claude's response
        comparison_data (dict): Vehicle comparison data
        
    Returns:
        str: Enhanced response with comparison information
    """
    if "error" in comparison_data:
        return f"{claude_response}\n\n{comparison_data['message']}"
    
    # Format vehicle names
    vehicle_names = [v["name"] for v in comparison_data["vehicles"]]
    vehicle_list = " and ".join(vehicle_names)
    
    # Format comparison introduction
    comparison_intro = f"Here's a comparison between the {vehicle_list}:"
    
    # Format comparison table
    comparison_table = "| Feature | " + " | ".join(vehicle_names) + " |\n"
    comparison_table += "| --- | " + " | ".join(["---"] * len(vehicle_names)) + " |\n"
    
    for feature, values in comparison_data["comparison_table"].items():
        feature_name = feature.replace("_", " ").title()
        comparison_table += f"| {feature_name} | " + " | ".join(str(v) for v in values) + " |\n"
    
    # Format key differences
    differences = ""
    if comparison_data["key_differences"]:
        differences = "**Key Differences:**\n- " + "\n- ".join(comparison_data["key_differences"])
    
    # Format recommendation
    recommendation = f"**Recommendation:** {comparison_data['recommendation']}" if comparison_data["recommendation"] else ""
    
    # Combine with Claude's response
    enhanced_response = f"{claude_response}\n\n{comparison_intro}\n\n{comparison_table}\n\n{differences}\n\n{recommendation}\n\nWould you like more specific details about either vehicle, or would you like to schedule a test drive to experience them yourself?"
    
    return enhanced_response
```

### User Flow

1. **User Query**: "Compare the 2023 Audi Q5 and 2023 Mercedes GLC"
2. **Intent Detection**: System identifies comparison intent and extracts vehicles
3. **Data Collection**: System collects comprehensive data for both vehicles
4. **Comparison Generation**: System generates detailed comparison
5. **Response Enhancement**: Claude's response is enhanced with comparison data
6. **User Response**: User can request more details, schedule a test drive, or ask follow-up questions

## Database Schema Updates

### Inventory Tracking Table
```sql
CREATE TABLE inventory_tracking (
    id SERIAL PRIMARY KEY,
    search_query TEXT NOT NULL,
    vehicles_found INTEGER NOT NULL,
    search_params JSONB NOT NULL,
    session_id VARCHAR(100),
    user_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Comparison Tracking Table
```sql
CREATE TABLE comparison_tracking (
    id SERIAL PRIMARY KEY,
    vehicles JSONB NOT NULL,
    session_id VARCHAR(100),
    user_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Analytics Implementation

### Inventory Search Analytics
```python
def track_inventory_search(search_params, results, session_id=None, user_id=None):
    """
    Track inventory search for analytics
    
    Args:
        search_params (dict): Search parameters
        results (dict): Search results
        session_id (str, optional): Session ID
        user_id (str, optional): User ID
    """
    query = """
    INSERT INTO inventory_tracking 
    (search_query, vehicles_found, search_params, session_id, user_id)
    VALUES (%s, %s, %s, %s, %s)
    """
    
    search_query = " ".join([f"{k}:{v}" for k, v in search_params.items()])
    
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query, 
                (
                    search_query, 
                    results["count"], 
                    json.dumps(search_params), 
                    session_id, 
                    user_id
                )
            )
```

### Comparison Analytics
```python
def track_vehicle_comparison(vehicles, session_id=None, user_id=None):
    """
    Track vehicle comparison for analytics
    
    Args:
        vehicles (list): Vehicles being compared
        session_id (str, optional): Session ID
        user_id (str, optional): User ID
    """
    query = """
    INSERT INTO comparison_tracking 
    (vehicles, session_id, user_id)
    VALUES (%s, %s, %s)
    """
    
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query, 
                (
                    json.dumps(vehicles), 
                    session_id, 
                    user_id
                )
            )
```

## Testing Strategy

### Unit Tests

```python
def test_inventory_search_intent_detection():
    """Test inventory search intent detection"""
    # Test positive case
    result = detect_inventory_search_intent("Do you have any Audi Q5s available under $50,000?")
    assert result["is_inventory_search"] == True
    assert result["params"]["make"] == "audi"
    assert result["params"]["model"] == "q5"
    assert result["params"]["max_price"] == 50000
    
    # Test negative case
    result = detect_inventory_search_intent("What are your dealership hours?")
    assert result["is_inventory_search"] == False

def test_comparison_intent_detection():
    """Test comparison intent detection"""
    # Test positive case
    result = detect_comparison_intent("Compare the 2023 Audi Q5 and 2023 Mercedes GLC")
    assert result["is_comparison"] == True
    assert len(result["vehicles"]) == 2
    assert result["vehicles"][0]["make"] == "audi"
    assert result["vehicles"][1]["make"] == "mercedes"
    
    # Test negative case
    result = detect_comparison_intent("Tell me about the 2023 Audi Q5")
    assert result["is_comparison"] == False
```

### Integration Tests

```python
def test_inventory_search_flow():
    """Test end-to-end inventory search flow"""
    user_message = "Do you have any Audi Q5s available under $50,000?"
    claude_response = "I'd be happy to check our inventory for Audi Q5s under $50,000."
    
    # Detect intent
    intent = detect_inventory_search_intent(user_message)
    assert intent["is_inventory_search"] == True
    
    # Process query
    results = process_inventory_query(intent["params"])
    
    # Enhance response
    enhanced_response = enhance_response_with_inventory(user_message, claude_response, results)
    
    assert "I found" in enhanced_response
    assert "Audi Q5" in enhanced_response
    assert "Price:" in enhanced_response

def test_comparison_flow():
    """Test end-to-end comparison flow"""
    user_message = "Compare the 2023 Audi Q5 and 2023 Mercedes GLC"
    claude_response = "I'd be happy to compare these two luxury SUVs for you."
    
    # Detect intent
    intent = detect_comparison_intent(user_message)
    assert intent["is_comparison"] == True
    
    # Collect vehicle data
    vehicle_data = collect_vehicle_data(intent["vehicles"])
    
    # Format comparison
    comparison = format_vehicle_comparison(vehicle_data)
    
    # Enhance response
    enhanced_response = enhance_response_with_comparison(user_message, claude_response, comparison)
    
    assert "comparison between" in enhanced_response
    assert "Audi Q5" in enhanced_response
    assert "Mercedes GLC" in enhanced_response
    assert "Key Differences" in enhanced_response
```

## Implementation Roadmap

### Phase 1: Core Components (1 week)
- Implement intent detection for inventory search and comparison
- Create database schema updates
- Set up analytics tracking

### Phase 2: Inventory Search (1 week)
- Implement inventory search query processor
- Create results formatter
- Integrate with Claude API
- Develop and test user flow

### Phase 3: Vehicle Comparison (1 week)
- Implement vehicle data collector
- Create comparison formatter
- Integrate with Claude API
- Develop and test user flow

### Phase 4: Testing and Optimization (1 week)
- Comprehensive testing of both features
- Performance optimization
- User experience refinement
- Documentation updates

## Success Metrics

- **Inventory Search Accuracy**: >90% correct identification of inventory search intent
- **Comparison Accuracy**: >90% correct identification of comparison intent
- **Response Time**: <1 second for inventory searches, <3 seconds for comparisons
- **User Satisfaction**: Measure improvement in user ratings for vehicle information
- **Conversion Rate**: Track increase in test drive bookings from inventory searches and comparisons
- **Engagement**: Measure increase in session duration and message count when these features are used

# Appointment Scheduling and Live Chat Handoff Implementation

## Overview
This document outlines the design and implementation of appointment scheduling and live chat handoff features for the Jack Ingram Motors chatbot. These features will enhance customer engagement by enabling seamless transitions from AI conversations to human interactions and allowing customers to schedule appointments directly through the chatbot.

## Appointment Scheduling Feature

### Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│             │     │                 │     │                 │
│  Chatbot UI │────▶│ Scheduling      │────▶│ Calendar        │
│             │     │ Intent Detector │     │ Service         │
└─────────────┘     └─────────────────┘     └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ Appointment     │
                                            │ Validator       │
                                            └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ Notification    │
                                            │ Service         │
                                            └─────────────────┘
```

### Components

#### 1. Scheduling Intent Detector
```python
def detect_scheduling_intent(user_message):
    """
    Detect if the user wants to schedule an appointment
    
    Args:
        user_message (str): The user's message
        
    Returns:
        dict: Intent detection results with confidence score and extracted parameters
    """
    # Keywords that suggest scheduling intent
    scheduling_keywords = [
        "schedule", "appointment", "book", "reserve", "test drive",
        "service", "maintenance", "oil change", "repair", "visit"
    ]
    
    # Check if message contains scheduling keywords
    has_scheduling_intent = any(keyword in user_message.lower() for keyword in scheduling_keywords)
    
    if not has_scheduling_intent:
        return {"is_scheduling": False}
    
    # Extract appointment type
    appointment_types = {
        "test drive": ["test drive", "test-drive", "drive", "try", "experience"],
        "service": ["service", "maintenance", "repair", "oil change", "tire", "brakes"],
        "sales": ["sales", "purchase", "buy", "finance", "lease", "discuss"]
    }
    
    appointment_type = None
    for type_name, keywords in appointment_types.items():
        if any(keyword in user_message.lower() for keyword in keywords):
            appointment_type = type_name
            break
    
    # Extract vehicle information if present
    vehicle_info = extract_vehicle_mentions(user_message)
    
    # Extract date/time preferences
    date_time_info = extract_date_time_preferences(user_message)
    
    return {
        "is_scheduling": True,
        "confidence": 0.8 if appointment_type else 0.6,
        "appointment_type": appointment_type,
        "vehicle_info": vehicle_info,
        "date_time_info": date_time_info
    }
```

#### 2. Date/Time Extractor
```python
def extract_date_time_preferences(user_message):
    """
    Extract date and time preferences from user message
    
    Args:
        user_message (str): The user's message
        
    Returns:
        dict: Extracted date and time preferences
    """
    # Initialize preferences
    preferences = {
        "date": None,
        "time": None,
        "day_of_week": None,
        "time_of_day": None,
        "is_specific": False
    }
    
    # Extract specific date (MM/DD/YYYY or Month DD)
    date_patterns = [
        r"(\d{1,2}/\d{1,2}/\d{4})",  # MM/DD/YYYY
        r"(\d{1,2}/\d{1,2})",  # MM/DD
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}"  # Month DD
    ]
    
    for pattern in date_patterns:
        matches = re.findall(pattern, user_message, re.IGNORECASE)
        if matches:
            preferences["date"] = matches[0]
            preferences["is_specific"] = True
            break
    
    # Extract specific time (HH:MM or H:MM AM/PM)
    time_patterns = [
        r"(\d{1,2}:\d{2})",  # HH:MM
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm))"  # H:MM AM/PM or H AM/PM
    ]
    
    for pattern in time_patterns:
        matches = re.findall(pattern, user_message, re.IGNORECASE)
        if matches:
            preferences["time"] = matches[0]
            preferences["is_specific"] = True
            break
    
    # Extract day of week
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for day in days:
        if day in user_message.lower():
            preferences["day_of_week"] = day
            break
    
    # Extract time of day
    time_periods = {
        "morning": ["morning", "am", "early"],
        "afternoon": ["afternoon", "noon", "lunch"],
        "evening": ["evening", "night", "pm", "late"]
    }
    
    for period, keywords in time_periods.items():
        if any(keyword in user_message.lower() for keyword in keywords):
            preferences["time_of_day"] = period
            break
    
    # Extract relative dates
    relative_dates = {
        "today": ["today", "this day"],
        "tomorrow": ["tomorrow"],
        "this week": ["this week"],
        "next week": ["next week"],
        "weekend": ["weekend", "saturday", "sunday"]
    }
    
    for rel_date, keywords in relative_dates.items():
        if any(keyword in user_message.lower() for keyword in keywords):
            preferences["relative_date"] = rel_date
            break
    
    return preferences
```

#### 3. Calendar Service
```python
def get_available_slots(appointment_type, date=None, time=None, day_of_week=None, time_of_day=None):
    """
    Get available appointment slots based on preferences
    
    Args:
        appointment_type (str): Type of appointment
        date (str, optional): Specific date
        time (str, optional): Specific time
        day_of_week (str, optional): Preferred day of week
        time_of_day (str, optional): Preferred time of day
        
    Returns:
        list: Available appointment slots
    """
    # Convert date string to datetime if provided
    target_date = None
    if date:
        try:
            # Try MM/DD/YYYY format
            target_date = datetime.strptime(date, "%m/%d/%Y")
        except ValueError:
            try:
                # Try MM/DD format (assume current year)
                target_date = datetime.strptime(f"{date}/{datetime.now().year}", "%m/%d/%Y")
            except ValueError:
                try:
                    # Try Month DD format
                    target_date = datetime.strptime(f"{date} {datetime.now().year}", "%B %d %Y")
                except ValueError:
                    pass
    
    # Handle relative dates
    if not target_date and "relative_date" in locals():
        relative_date = locals()["relative_date"]
        today = datetime.now().date()
        
        if relative_date == "today":
            target_date = today
        elif relative_date == "tomorrow":
            target_date = today + timedelta(days=1)
        elif relative_date == "this week":
            # Find next business day this week
            days_ahead = 1 - today.weekday()  # 1 = Tuesday
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            target_date = today + timedelta(days=days_ahead)
        elif relative_date == "next week":
            # Find same day next week
            target_date = today + timedelta(days=7)
        elif relative_date == "weekend":
            # Find next Saturday
            days_ahead = 5 - today.weekday()  # 5 = Saturday
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            target_date = today + timedelta(days=days_ahead)
    
    # If day of week is specified but no specific date
    if not target_date and day_of_week:
        today = datetime.now().date()
        day_to_num = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6
        }
        target_day = day_to_num.get(day_of_week.lower())
        if target_day is not None:
            days_ahead = target_day - today.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            target_date = today + timedelta(days=days_ahead)
    
    # If no date is specified, default to tomorrow
    if not target_date:
        tomorrow = datetime.now().date() + timedelta(days=1)
        target_date = tomorrow
    
    # Query database for available slots
    query = """
    SELECT slot_time, slot_date
    FROM appointment_slots
    WHERE slot_date = %s
    AND appointment_type = %s
    AND is_available = TRUE
    """
    
    params = [target_date, appointment_type]
    
    # Add time of day filter if specified
    if time_of_day:
        time_ranges = {
            "morning": ("08:00:00", "11:59:59"),
            "afternoon": ("12:00:00", "16:59:59"),
            "evening": ("17:00:00", "20:00:00")
        }
        if time_of_day in time_ranges:
            query += " AND slot_time BETWEEN %s AND %s"
            params.extend(time_ranges[time_of_day])
    
    # Execute query
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            available_slots = cursor.fetchall()
    
    # Format results
    formatted_slots = []
    for slot in available_slots:
        slot_time = slot[0]
        slot_date = slot[1]
        formatted_slots.append({
            "date": slot_date.strftime("%A, %B %d, %Y"),
            "time": slot_time.strftime("%I:%M %p"),
            "datetime": f"{slot_date.strftime('%Y-%m-%d')}T{slot_time.strftime('%H:%M:%S')}",
            "appointment_type": appointment_type
        })
    
    return formatted_slots
```

#### 4. Appointment Booking
```python
def book_appointment(appointment_type, slot_datetime, customer_info, vehicle_info=None):
    """
    Book an appointment
    
    Args:
        appointment_type (str): Type of appointment
        slot_datetime (str): ISO format datetime string
        customer_info (dict): Customer contact information
        vehicle_info (dict, optional): Vehicle information
        
    Returns:
        dict: Booking confirmation
    """
    # Parse datetime
    try:
        dt = datetime.fromisoformat(slot_datetime)
        slot_date = dt.date()
        slot_time = dt.time()
    except ValueError:
        return {
            "success": False,
            "error": "Invalid datetime format"
        }
    
    # Validate slot availability
    query = """
    SELECT id FROM appointment_slots
    WHERE slot_date = %s
    AND slot_time = %s
    AND appointment_type = %s
    AND is_available = TRUE
    """
    
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, [slot_date, slot_time, appointment_type])
            slot = cursor.fetchone()
            
            if not slot:
                return {
                    "success": False,
                    "error": "Slot is no longer available"
                }
            
            slot_id = slot[0]
            
            # Insert appointment
            insert_query = """
            INSERT INTO appointments
            (customer_name, customer_email, customer_phone, appointment_type, 
             appointment_date, appointment_time, vehicle_info, notes, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'scheduled')
            RETURNING id
            """
            
            cursor.execute(
                insert_query,
                [
                    customer_info.get("name"),
                    customer_info.get("email"),
                    customer_info.get("phone"),
                    appointment_type,
                    slot_date,
                    slot_time,
                    json.dumps(vehicle_info) if vehicle_info else None,
                    customer_info.get("notes")
                ]
            )
            
            appointment_id = cursor.fetchone()[0]
            
            # Mark slot as unavailable
            update_query = """
            UPDATE appointment_slots
            SET is_available = FALSE, appointment_id = %s
            WHERE id = %s
            """
            
            cursor.execute(update_query, [appointment_id, slot_id])
            
            # Commit transaction
            conn.commit()
    
    # Generate confirmation
    confirmation = {
        "success": True,
        "appointment_id": appointment_id,
        "appointment_type": appointment_type,
        "date": dt.strftime("%A, %B %d, %Y"),
        "time": dt.strftime("%I:%M %p"),
        "customer_name": customer_info.get("name"),
        "confirmation_code": generate_confirmation_code(appointment_id)
    }
    
    # Send confirmation notifications
    send_appointment_confirmation(confirmation, customer_info.get("email"))
    
    return confirmation
```

#### 5. Notification Service
```python
def send_appointment_confirmation(confirmation, email):
    """
    Send appointment confirmation email
    
    Args:
        confirmation (dict): Appointment confirmation details
        email (str): Customer email address
    """
    subject = f"Your {confirmation['appointment_type']} appointment confirmation"
    
    body = f"""
    Dear {confirmation['customer_name']},
    
    Thank you for scheduling an appointment with Jack Ingram Motors. Your appointment details are:
    
    Appointment Type: {confirmation['appointment_type'].title()}
    Date: {confirmation['date']}
    Time: {confirmation['time']}
    Confirmation Code: {confirmation['confirmation_code']}
    
    If you need to reschedule or cancel, please call us at (555) 123-4567 or reply to this email.
    
    We look forward to seeing you!
    
    Best regards,
    Jack Ingram Motors Team
    """
    
    # Send email using SMTP
    send_email(email, subject, body)
    
    # Also send SMS if phone number is available
    # send_sms(phone, f"Your {confirmation['appointment_type']} appointment is confirmed for {confirmation['date']} at {confirmation['time']}. Confirmation code: {confirmation['confirmation_code']}")
```

#### 6. Claude Integration
```python
def handle_scheduling_flow(user_message, claude_response, scheduling_intent):
    """
    Handle the appointment scheduling conversation flow
    
    Args:
        user_message (str): Original user message
        claude_response (str): Claude's response
        scheduling_intent (dict): Detected scheduling intent
        
    Returns:
        dict: Next step in the scheduling flow
    """
    # Extract intent details
    appointment_type = scheduling_intent.get("appointment_type")
    date_time_info = scheduling_intent.get("date_time_info", {})
    vehicle_info = scheduling_intent.get("vehicle_info")
    
    # If appointment type is not specified, ask for it
    if not appointment_type:
        return {
            "status": "need_appointment_type",
            "message": f"{claude_response}\n\nI'd be happy to help you schedule an appointment. What type of appointment would you like to schedule? We offer test drives, service appointments, and sales consultations."
        }
    
    # Get available slots based on preferences
    available_slots = get_available_slots(
        appointment_type=appointment_type,
        date=date_time_info.get("date"),
        time=date_time_info.get("time"),
        day_of_week=date_time_info.get("day_of_week"),
        time_of_day=date_time_info.get("time_of_day")
    )
    
    if not available_slots:
        # No slots available for the requested time
        return {
            "status": "no_slots_available",
            "message": f"{claude_response}\n\nI'm sorry, but we don't have any {appointment_type} appointments available at the requested time. Would you like to try a different day or time?"
        }
    
    # Format available slots for presentation
    slots_text = "Here are the available appointment times:\n\n"
    for i, slot in enumerate(available_slots[:5], 1):
        slots_text += f"{i}. {slot['date']} at {slot['time']}\n"
    
    return {
        "status": "slots_available",
        "message": f"{claude_response}\n\n{slots_text}\n\nWhich time would you prefer? You can select by number or specify another day if none of these work for you.",
        "available_slots": available_slots[:5]
    }
```

### User Flow

1. **User Query**: "I'd like to schedule a test drive for an Audi Q5 this Saturday"
2. **Intent Detection**: System identifies scheduling intent and extracts parameters (appointment_type: test drive, vehicle: Audi Q5, day: Saturday)
3. **Slot Availability**: System checks for available slots on Saturday
4. **Slot Presentation**: Claude presents available time slots
5. **Slot Selection**: User selects a time slot
6. **Information Collection**: System collects user contact information
7. **Confirmation**: System books appointment and sends confirmation
8. **Follow-up**: Claude confirms booking and offers next steps

## Live Chat Handoff Feature

### Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│             │     │                 │     │                 │
│  Chatbot UI │────▶│ Handoff         │────▶│ Agent           │
│             │     │ Intent Detector │     │ Availability    │
└─────────────┘     └─────────────────┘     └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ Conversation    │
                                            │ Context Builder │
                                            └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ Live Chat       │
                                            │ System          │
                                            └─────────────────┘
```

### Components

#### 1. Handoff Intent Detector
```python
def detect_handoff_intent(user_message, conversation_history):
    """
    Detect if the user wants to speak with a human agent
    
    Args:
        user_message (str): The user's message
        conversation_history (list): Previous messages in the conversation
        
    Returns:
        dict: Intent detection results with confidence score and reason
    """
    # Keywords that suggest handoff intent
    handoff_keywords = [
        "speak to human", "talk to human", "speak to agent", "talk to agent",
        "speak to representative", "talk to representative", "speak to person",
        "talk to person", "human agent", "real person", "transfer me"
    ]
    
    # Check if message contains handoff keywords
    explicit_handoff = any(keyword in user_message.lower() for keyword in handoff_keywords)
    
    if explicit_handoff:
        return {
            "needs_handoff": True,
            "confidence": 0.9,
            "reason": "explicit_request",
            "urgency": "high"
        }
    
    # Check for frustration indicators
    frustration_keywords = [
        "not helpful", "doesn't understand", "don't understand", "confused",
        "frustrating", "frustrated", "not working", "wrong", "incorrect",
        "stop", "quit", "give up", "useless", "waste of time"
    ]
    
    frustration_detected = any(keyword in user_message.lower() for keyword in frustration_keywords)
    
    if frustration_detected:
        return {
            "needs_handoff": True,
            "confidence": 0.7,
            "reason": "user_frustration",
            "urgency": "medium"
        }
    
    # Check for complex queries that might need human assistance
    complex_topics = [
        "financing", "lease", "trade-in value", "negotiation", "discount",
        "special offer", "warranty claim", "complaint", "problem", "issue"
    ]
    
    complex_query = any(topic in user_message.lower() for topic in complex_topics)
    
    if complex_query:
        return {
            "needs_handoff": True,
            "confidence": 0.6,
            "reason": "complex_query",
            "urgency": "medium"
        }
    
    # Check for repeated questions (potential confusion)
    if len(conversation_history) >= 4:
        recent_messages = [msg["content"] for msg in conversation_history[-4:] if msg["role"] == "user"]
        similar_messages = check_message_similarity(recent_messages)
        
        if similar_messages:
            return {
                "needs_handoff": True,
                "confidence": 0.5,
                "reason": "repeated_questions",
                "urgency": "low"
            }
    
    return {
        "needs_handoff": False,
        "confidence": 0.0
    }
```

#### 2. Agent Availability Service
```python
def check_agent_availability(department=None):
    """
    Check if human agents are available
    
    Args:
        department (str, optional): Specific department to check
        
    Returns:
        dict: Availability information
    """
    # Get current time in dealership timezone
    now = datetime.now(pytz.timezone('America/Chicago'))
    current_time = now.time()
    current_day = now.strftime('%A').lower()
    
    # Check if within business hours
    business_hours = {
        'monday': {'start': time(8, 0), 'end': time(20, 0)},
        'tuesday': {'start': time(8, 0), 'end': time(20, 0)},
        'wednesday': {'start': time(8, 0), 'end': time(20, 0)},
        'thursday': {'start': time(8, 0), 'end': time(20, 0)},
        'friday': {'start': time(8, 0), 'end': time(20, 0)},
        'saturday': {'start': time(9, 0), 'end': time(18, 0)},
        'sunday': {'start': time(12, 0), 'end': time(17, 0)}
    }
    
    if current_day in business_hours:
        hours = business_hours[current_day]
        within_hours = hours['start'] <= current_time <= hours['end']
    else:
        within_hours = False
    
    if not within_hours:
        return {
            "available": False,
            "reason": "outside_business_hours",
            "next_available": get_next_business_hours(now, business_hours)
        }
    
    # Check agent availability in database
    query = """
    SELECT 
        department,
        COUNT(*) as total_agents,
        SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END) as available_agents,
        SUM(CASE WHEN status = 'busy' THEN 1 ELSE 0 END) as busy_agents
    FROM agent_status
    WHERE is_online = TRUE
    """
    
    if department:
        query += " AND department = %s"
        query += " GROUP BY department"
        params = [department]
    else:
        query += " GROUP BY department"
        params = []
    
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
    
    if not results:
        return {
            "available": False,
            "reason": "no_agents_online",
            "estimated_wait_time": None
        }
    
    # Process results
    departments = {}
    for row in results:
        dept = row[0]
        total = row[1]
        available = row[2]
        busy = row[3]
        
        departments[dept] = {
            "total_agents": total,
            "available_agents": available,
            "busy_agents": busy,
            "available": available > 0,
            "estimated_wait_time": calculate_wait_time(available, busy) if busy > 0 and available == 0 else 0
        }
    
    # If specific department was requested
    if department and department in departments:
        dept_info = departments[department]
        return {
            "available": dept_info["available"],
            "department": department,
            "estimated_wait_time": dept_info["estimated_wait_time"],
            "reason": "agents_busy" if not dept_info["available"] else None
        }
    
    # Check if any department has available agents
    any_available = any(dept["available"] for dept in departments.values())
    
    if any_available:
        # Find department with most available agents
        best_dept = max(departments.items(), key=lambda x: x[1]["available_agents"])
        return {
            "available": True,
            "department": best_dept[0],
            "available_agents": best_dept[1]["available_agents"],
            "estimated_wait_time": 0
        }
    else:
        # Calculate minimum wait time across departments
        wait_times = [dept["estimated_wait_time"] for dept in departments.values() if dept["estimated_wait_time"] is not None]
        min_wait = min(wait_times) if wait_times else None
        
        return {
            "available": False,
            "reason": "all_agents_busy",
            "estimated_wait_time": min_wait
        }
```

#### 3. Conversation Context Builder
```python
def build_conversation_context(conversation_history, user_info=None, vehicle_info=None):
    """
    Build context summary for agent handoff
    
    Args:
        conversation_history (list): Previous messages in the conversation
        user_info (dict, optional): User information
        vehicle_info (dict, optional): Vehicle information the user is interested in
        
    Returns:
        dict: Conversation context for agent
    """
    # Extract key information from conversation
    topics = extract_conversation_topics(conversation_history)
    
    # Summarize recent conversation
    recent_messages = conversation_history[-10:] if len(conversation_history) > 10 else conversation_history
    summary = summarize_conversation(recent_messages)
    
    # Identify user needs and interests
    interests = identify_user_interests(conversation_history)
    
    # Format context for agent
    context = {
        "conversation_summary": summary,
        "topics_discussed": topics,
        "user_interests": interests,
        "conversation_length": len(conversation_history),
        "conversation_duration": calculate_conversation_duration(conversation_history),
        "full_history": conversation_history
    }
    
    # Add user info if available
    if user_info:
        context["user_info"] = user_info
    
    # Add vehicle info if available
    if vehicle_info:
        context["vehicle_info"] = vehicle_info
    
    return context
```

#### 4. Handoff Manager
```python
def initiate_handoff(user_id, session_id, conversation_context, department=None):
    """
    Initiate handoff to human agent
    
    Args:
        user_id (str): User identifier
        session_id (str): Session identifier
        conversation_context (dict): Conversation context
        department (str, optional): Specific department for handoff
        
    Returns:
        dict: Handoff status and information
    """
    # Check agent availability
    availability = check_agent_availability(department)
    
    if not availability["available"]:
        if availability["reason"] == "outside_business_hours":
            return {
                "status": "scheduled",
                "message": f"Our agents are currently unavailable as we're outside business hours. The next available time is {availability['next_available']}. Would you like to schedule a callback?",
                "next_available": availability["next_available"]
            }
        else:
            wait_time = availability["estimated_wait_time"] or "unknown"
            return {
                "status": "queued",
                "message": f"All our agents are currently assisting other customers. The estimated wait time is {wait_time} minutes. Would you like to wait, or schedule a callback?",
                "estimated_wait_time": wait_time
            }
    
    # Create handoff record
    handoff_id = create_handoff_record(user_id, session_id, conversation_context, department)
    
    # Notify available agent
    agent_id = notify_agent(handoff_id, department)
    
    if not agent_id:
        return {
            "status": "error",
            "message": "There was an error connecting you with an agent. Please try again."
        }
    
    return {
        "status": "connected",
        "message": f"You're being connected to an agent who will continue this conversation. Please wait a moment.",
        "handoff_id": handoff_id,
        "agent_id": agent_id
    }
```

#### 5. Claude Integration
```python
def handle_handoff_flow(user_message, claude_response, handoff_intent, conversation_history):
    """
    Handle the live chat handoff conversation flow
    
    Args:
        user_message (str): Original user message
        claude_response (str): Claude's response
        handoff_intent (dict): Detected handoff intent
        conversation_history (list): Previous messages in the conversation
        
    Returns:
        dict: Next step in the handoff flow
    """
    # If no handoff needed, return original response
    if not handoff_intent["needs_handoff"]:
        return {
            "status": "continue_with_claude",
            "message": claude_response
        }
    
    # Check agent availability
    department = determine_appropriate_department(handoff_intent, conversation_history)
    availability = check_agent_availability(department)
    
    # Build conversation context
    context = build_conversation_context(conversation_history)
    
    # If agents are available, initiate handoff
    if availability["available"]:
        handoff_result = initiate_handoff(
            user_id=get_user_id_from_session(),
            session_id=get_session_id(),
            conversation_context=context,
            department=department
        )
        
        if handoff_result["status"] == "connected":
            return {
                "status": "handoff_initiated",
                "message": f"I understand you'd like to speak with a human agent. I'm connecting you with a {department} specialist now. They'll have access to our conversation history so you won't need to repeat yourself. Please wait just a moment while I transfer you.",
                "handoff_id": handoff_result["handoff_id"]
            }
        else:
            return {
                "status": "handoff_queued",
                "message": f"I understand you'd like to speak with a human agent. {handoff_result['message']}",
                "wait_info": handoff_result
            }
    else:
        # Agents not available
        if availability["reason"] == "outside_business_hours":
            return {
                "status": "offer_callback",
                "message": f"I understand you'd like to speak with a human agent. Our agents are currently unavailable as we're outside business hours. The next available time is {availability['next_available']}. Would you like me to schedule a callback for you, or is there something I can help with in the meantime?",
                "next_available": availability["next_available"]
            }
        else:
            wait_time = availability["estimated_wait_time"] or "a few"
            return {
                "status": "offer_wait_or_callback",
                "message": f"I understand you'd like to speak with a human agent. All our agents are currently assisting other customers. The estimated wait time is {wait_time} minutes. Would you like to wait in queue, schedule a callback, or is there something I can help with in the meantime?",
                "estimated_wait_time": wait_time
            }
```

### User Flow

1. **User Query**: "I need to speak with a human agent about financing options"
2. **Intent Detection**: System identifies handoff intent and reason (complex query: financing)
3. **Agent Availability**: System checks for available agents in the sales/finance department
4. **Context Building**: System builds conversation context for agent handoff
5. **Handoff Initiation**: Claude informs user of handoff and initiates transfer
6. **Agent Connection**: Human agent receives context and continues conversation
7. **Post-Handoff**: System records handoff metrics and outcomes

## Database Schema Updates

### Appointment Slots Table
```sql
CREATE TABLE appointment_slots (
    id SERIAL PRIMARY KEY,
    slot_date DATE NOT NULL,
    slot_time TIME NOT NULL,
    appointment_type VARCHAR(50) NOT NULL,
    is_available BOOLEAN DEFAULT TRUE,
    appointment_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Agent Status Table
```sql
CREATE TABLE agent_status (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(50) NOT NULL,
    agent_name VARCHAR(100) NOT NULL,
    department VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'available',
    is_online BOOLEAN DEFAULT FALSE,
    last_activity TIMESTAMP,
    current_handoff_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Handoff Records Table
```sql
CREATE TABLE handoff_records (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100),
    session_id VARCHAR(100) NOT NULL,
    agent_id VARCHAR(50),
    department VARCHAR(50),
    handoff_reason VARCHAR(50),
    conversation_context JSONB,
    status VARCHAR(20) DEFAULT 'initiated',
    wait_time INTEGER,
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    customer_satisfaction INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Analytics Implementation

### Appointment Analytics
```python
def track_appointment_scheduling(appointment_type, slot_selected, session_id=None, user_id=None):
    """
    Track appointment scheduling for analytics
    
    Args:
        appointment_type (str): Type of appointment
        slot_selected (dict): Selected time slot
        session_id (str, optional): Session ID
        user_id (str, optional): User ID
    """
    query = """
    INSERT INTO appointment_analytics 
    (appointment_type, slot_date, slot_time, session_id, user_id)
    VALUES (%s, %s, %s, %s, %s)
    """
    
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query, 
                (
                    appointment_type,
                    slot_selected["date"],
                    slot_selected["time"],
                    session_id,
                    user_id
                )
            )
```

### Handoff Analytics
```python
def track_handoff_analytics(handoff_id, outcome, duration, customer_satisfaction=None):
    """
    Track handoff analytics
    
    Args:
        handoff_id (int): Handoff record ID
        outcome (str): Outcome of the handoff
        duration (int): Duration of handoff in seconds
        customer_satisfaction (int, optional): Customer satisfaction rating
    """
    query = """
    UPDATE handoff_records
    SET status = %s, end_time = NOW(), wait_time = %s, customer_satisfaction = %s
    WHERE id = %s
    """
    
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query, 
                (
                    outcome,
                    duration,
                    customer_satisfaction,
                    handoff_id
                )
            )
```

## Testing Strategy

### Unit Tests

```python
def test_scheduling_intent_detection():
    """Test scheduling intent detection"""
    # Test positive case
    result = detect_scheduling_intent("I'd like to schedule a test drive for an Audi Q5 this Saturday")
    assert result["is_scheduling"] == True
    assert result["appointment_type"] == "test drive"
    assert result["date_time_info"]["day_of_week"] == "saturday"
    
    # Test negative case
    result = detect_scheduling_intent("What are the specs of the Audi Q5?")
    assert result["is_scheduling"] == False

def test_handoff_intent_detection():
    """Test handoff intent detection"""
    # Test explicit request
    result = detect_handoff_intent("I want to speak to a human agent", [])
    assert result["needs_handoff"] == True
    assert result["reason"] == "explicit_request"
    
    # Test frustration detection
    result = detect_handoff_intent("This is frustrating, you're not understanding me", [])
    assert result["needs_handoff"] == True
    assert result["reason"] == "user_frustration"
```

### Integration Tests

```python
def test_scheduling_flow():
    """Test end-to-end scheduling flow"""
    user_message = "I'd like to schedule a test drive for an Audi Q5 this Saturday"
    claude_response = "I'd be happy to help you schedule a test drive."
    
    # Detect intent
    intent = detect_scheduling_intent(user_message)
    assert intent["is_scheduling"] == True
    
    # Handle scheduling flow
    result = handle_scheduling_flow(user_message, claude_response, intent)
    
    assert "available appointment times" in result["message"].lower()
    assert len(result["available_slots"]) > 0

def test_handoff_flow():
    """Test end-to-end handoff flow"""
    user_message = "I want to speak to a human agent about financing"
    claude_response = "I can help with financing questions."
    conversation_history = [
        {"role": "user", "content": "I'm interested in the Audi Q5"},
        {"role": "assistant", "content": "The Audi Q5 is a luxury SUV with..."},
        {"role": "user", "content": user_message}
    ]
    
    # Detect intent
    intent = detect_handoff_intent(user_message, conversation_history)
    assert intent["needs_handoff"] == True
    
    # Handle handoff flow
    result = handle_handoff_flow(user_message, claude_response, intent, conversation_history)
    
    assert "human agent" in result["message"].lower()
    assert result["status"] in ["handoff_initiated", "handoff_queued", "offer_callback", "offer_wait_or_callback"]
```

## Implementation Roadmap

### Phase 1: Appointment Scheduling (1 week)
- Implement scheduling intent detection
- Create database schema for appointment slots
- Develop calendar service and slot availability
- Integrate with Claude API
- Develop and test user flow

### Phase 2: Live Chat Handoff (1 week)
- Implement handoff intent detection
- Create agent availability service
- Develop conversation context builder
- Integrate with Claude API
- Develop and test user flow

### Phase 3: Notification System (3 days)
- Implement email notifications for appointments
- Create SMS notification capability
- Develop reminder system

### Phase 4: Agent Dashboard (4 days)
- Create agent interface for handling handoffs
- Develop conversation history viewer
- Implement status management
- Create handoff queue management

### Phase 5: Testing and Optimization (3 days)
- Comprehensive testing of both features
- Performance optimization
- User experience refinement
- Documentation updates

## Success Metrics

- **Appointment Scheduling Completion Rate**: >80% of started scheduling flows result in confirmed appointments
- **Handoff Success Rate**: >90% of handoff requests successfully connect with human agents
- **Agent Response Time**: <30 seconds average response time after handoff
- **Customer Satisfaction**: >4.5/5 average rating for appointments and handoffs
- **Conversion Rate**: Track increase in test drive to purchase conversion rate
- **Agent Efficiency**: Measure reduction in average handling time with context-rich handoffs

# Lead Capture, CRM Integration, and Feedback Collection Implementation

## Overview
This document outlines the design and implementation of enhanced lead capture, CRM integration, and feedback collection features for the Jack Ingram Motors chatbot. These features are crucial for converting visitors into actionable leads, streamlining sales processes, and continuously improving the chatbot's performance based on user input.

## Lead Capture Feature

### Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│             │     │                 │     │                 │
│  Chatbot UI │────▶│ Lead Capture    │────▶│ Data Validation │
│             │     │ Trigger         │     │ Service         │
└─────────────┘     └─────────────────┘     └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ Lead Storage /  │
                                            │ CRM Integration │
                                            └─────────────────┘
```

### Components

#### 1. Lead Capture Trigger
```python
def detect_lead_capture_trigger(user_message, conversation_context):
    """
    Detect if the conversation has reached a point for lead capture.
    
    Args:
        user_message (str): The user's current message.
        conversation_context (dict): Context of the ongoing conversation (e.g., intents, entities, history).
        
    Returns:
        dict: Trigger detection results with confidence and reason.
    """
    triggers = {
        "explicit_request_quote": ["quote", "price", "cost", "how much"],
        "test_drive_interest": ["test drive", "try the car"],
        "financing_inquiry": ["financing", "loan", "lease options"],
        "specific_vehicle_deep_interest": ["details on VIN", "availability of stock #"],
        "end_of_helpful_interaction": ["thanks that was helpful", "appreciate the info"],
        "unresolved_complex_query": ["cannot_answer_fully_trigger"]
    }
    
    # Check for explicit requests or strong indicators
    for reason, keywords in triggers.items():
        if any(keyword in user_message.lower() for keyword in keywords):
            return {"should_capture_lead": True, "reason": reason, "confidence": 0.85}
    
    # Check conversation context for implicit triggers
    if conversation_context.get("intent") == "request_information" and conversation_context.get("consecutive_vehicle_questions", 0) >= 3:
        return {"should_capture_lead": True, "reason": "sustained_vehicle_interest", "confidence": 0.7}

    if conversation_context.get("task_completed") == "appointment_scheduled":
         return {"should_capture_lead": True, "reason": "post_appointment_booking", "confidence": 0.9}

    return {"should_capture_lead": False}
```

#### 2. Lead Form Presentation (Dynamic)
```python
def present_lead_form(reason, existing_data=None):
    """
    Dynamically present a lead capture form based on the trigger reason.
    
    Args:
        reason (str): The reason lead capture was triggered.
        existing_data (dict, optional): Any data already collected (e.g., from chat history).
        
    Returns:
        dict: Form structure with fields to be presented to the user.
    """
    form_fields = [
        {"name": "full_name", "label": "Full Name", "type": "text", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": True},
        {"name": "phone", "label": "Phone Number", "type": "tel", "required": False}
    ]
    
    # Add context-specific fields
    if reason in ["explicit_request_quote", "specific_vehicle_deep_interest", "sustained_vehicle_interest"]:
        form_fields.append({"name": "vehicle_of_interest", "label": "Vehicle of Interest (e.g., 2023 Audi Q5)", "type": "text", "required": False, "value": existing_data.get("vehicle_of_interest", "")})
    
    if reason == "test_drive_interest":
        form_fields.append({"name": "preferred_test_drive_date", "label": "Preferred Test Drive Date", "type": "date", "required": False})

    form_fields.append({"name": "preferred_contact_method", "label": "Preferred Contact Method", "type": "select", "options": ["Email", "Phone", "Text"], "required": False})
    form_fields.append({"name": "additional_comments", "label": "Any additional comments or questions?", "type": "textarea", "required": False})
    
    # Pre-fill known data
    if existing_data:
        for field in form_fields:
            if field["name"] in existing_data and not field.get("value"):
                field["value"] = existing_data[field["name"]]
                
    return {
        "title": "Let's get some details to assist you further",
        "fields": form_fields,
        "submit_button_text": "Submit Information"
    }
```

#### 3. Data Validation Service
```python
import re

def validate_lead_data(data):
    """
    Validate submitted lead data.
    
    Args:
        data (dict): Submitted lead data.
        
    Returns:
        dict: Validation results (is_valid, errors).
    """
    errors = {}
    is_valid = True
    
    # Validate Full Name (basic check)
    if not data.get("full_name") or len(data["full_name"].strip()) < 2:
        errors["full_name"] = "Please enter a valid full name."
        is_valid = False
        
    # Validate Email
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$
    if not data.get("email") or not re.match(email_regex, data["email"]):
        errors["email"] = "Please enter a valid email address."
        is_valid = False
        
    # Validate Phone (optional, but if provided, check format)
    phone_regex = r"^\+?[1-9]\d{1,14}$" # E.164 format (simplified)
    if data.get("phone") and not re.match(phone_regex, data["phone"].replace(" ", "").replace("-", "").replace("(", "").replace(")", "")):
        errors["phone"] = "Please enter a valid phone number (e.g., +12223334444)."
        is_valid = False
        
    return {"is_valid": is_valid, "errors": errors, "validated_data": data if is_valid else None}
```

## CRM Integration

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│                 │     │                 │     │                 │
│ Lead Storage /  │────▶│ CRM Mapper      │────▶│ CRM API Client  │
│ Data Validation │     │                 │     │ (e.g.,         │
└─────────────────┘     └─────────────────┘     │ Salesforce,     │
                                                │ HubSpot)        │
                                                └─────────────────┘
```

### Components

#### 1. CRM Mapper
```python
def map_to_crm_fields(lead_data, crm_type="generic"):
    """
    Map chatbot lead data to CRM-specific fields.
    
    Args:
        lead_data (dict): Validated lead data from the chatbot.
        crm_type (str): Type of CRM (e.g., "salesforce", "hubspot", "dealersocket").
        
    Returns:
        dict: Data mapped to CRM fields.
    """
    mapped_data = {}
    
    if crm_type == "salesforce":
        mapped_data["FirstName"] = lead_data.get("full_name", "").split(" ", 1)[0] if lead_data.get("full_name") else ""
        mapped_data["LastName"] = lead_data.get("full_name", "").split(" ", 1)[1] if " " in lead_data.get("full_name", "") else "Lead"
        mapped_data["Email"] = lead_data.get("email")
        mapped_data["Phone"] = lead_data.get("phone")
        mapped_data["LeadSource"] = "Chatbot - Jack Ingram"
        mapped_data["Description"] = f"Vehicle of Interest: {lead_data.get("vehicle_of_interest", "N/A")}\nComments: {lead_data.get("additional_comments", "N/A")}"
        # Add other Salesforce-specific fields
    elif crm_type == "hubspot":
        mapped_data["properties"] = [
            {"property": "firstname", "value": lead_data.get("full_name", "").split(" ", 1)[0] if lead_data.get("full_name") else ""},
            {"property": "lastname", "value": lead_data.get("full_name", "").split(" ", 1)[1] if " " in lead_data.get("full_name", "") else "Lead"},
            {"property": "email", "value": lead_data.get("email")},
            {"property": "phone", "value": lead_data.get("phone")},
            {"property": "hs_lead_status", "value": "NEW"},
            {"property": "vehicle_of_interest_chatbot__c", "value": lead_data.get("vehicle_of_interest")},
            # Add other HubSpot-specific fields
        ]
    else: # Generic mapping
        mapped_data["name"] = lead_data.get("full_name")
        mapped_data["email_address"] = lead_data.get("email")
        mapped_data["phone_number"] = lead_data.get("phone")
        mapped_data["source"] = "Chatbot"
        mapped_data["notes"] = f"Vehicle: {lead_data.get("vehicle_of_interest")}. Comments: {lead_data.get("additional_comments")}"
        
    return mapped_data
```

#### 2. CRM API Client (Generic Example)
```python
import requests
import json

def push_lead_to_crm(mapped_lead_data, crm_config):
    """
    Push lead data to the configured CRM.
    
    Args:
        mapped_lead_data (dict): Lead data mapped to CRM fields.
        crm_config (dict): Configuration for the CRM (api_url, api_key, etc.).
        
    Returns:
        dict: CRM API response (success, crm_lead_id, error).
    """
    headers = {
        "Authorization": f"Bearer {crm_config.get("api_key")}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(crm_config.get("api_url"), headers=headers, data=json.dumps(mapped_lead_data), timeout=10)
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        
        response_data = response.json()
        return {"success": True, "crm_lead_id": response_data.get("id"), "message": "Lead created successfully."}
    
    except requests.exceptions.RequestException as e:
        # Log error: e.g., logger.error(f"CRM API Error: {e}")
        # Fallback: Save lead to local DB or queue for retry
        save_lead_locally(mapped_lead_data, error=str(e))
        return {"success": False, "error": str(e), "message": "Failed to create lead in CRM. Saved locally."}

# Fallback mechanism
def save_lead_locally(lead_data, error=None):
    """Save lead to a local database or file if CRM push fails."""
    # Implementation for local storage (e.g., to leads table in project DB)
    # db_connection.execute("INSERT INTO pending_crm_leads (data, error_message) VALUES (%s, %s)", (json.dumps(lead_data), error))
    pass
```

## Feedback Collection Feature

### Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│             │     │                 │     │                 │
│  Chatbot UI │────▶│ Feedback        │────▶│ Feedback Form   │
│             │     │ Trigger         │     │ Presenter       │
└─────────────┘     └─────────────────┘     └────────┬────────┘
                                                     │
                                                     ▼
                                            ┌─────────────────┐
                                            │                 │
                                            │ Feedback        │
                                            │ Storage/Analysis│
                                            └─────────────────┘
```

### Components

#### 1. Feedback Trigger
```python
def detect_feedback_trigger(conversation_context):
    """
    Detect if it's an appropriate time to ask for feedback.
    
    Args:
        conversation_context (dict): Context of the conversation.
        
    Returns:
        bool: True if feedback should be requested.
    """
    # Trigger after a certain number of turns or task completion
    if conversation_context.get("turns", 0) >= 5 and not conversation_context.get("feedback_requested_this_session", False):
        return True
    if conversation_context.get("task_completed") and not conversation_context.get("feedback_requested_this_session", False):
        return True
    if conversation_context.get("session_end_signal", False) and not conversation_context.get("feedback_requested_this_session", False):
        return True
        
    return False
```

#### 2. Feedback Form Presenter
```python
def present_feedback_form():
    """
    Present a feedback collection form.
    
    Returns:
        dict: Form structure for feedback.
    """
    return {
        "title": "How was your experience today?",
        "fields": [
            {"name": "rating", "label": "Overall, how satisfied were you with our chatbot today? (1=Very Dissatisfied, 5=Very Satisfied)", "type": "radio", "options": ["1", "2", "3", "4", "5"], "required": True},
            {"name": "ease_of_use", "label": "How easy was it to get the information you needed? (1=Very Difficult, 5=Very Easy)", "type": "radio", "options": ["1", "2", "3", "4", "5"], "required": False},
            {"name": "comments", "label": "Do you have any additional comments or suggestions for improvement?", "type": "textarea", "required": False}
        ],
        "submit_button_text": "Submit Feedback"
    }
```

#### 3. Feedback Storage and Analysis
```python
def store_feedback(feedback_data, session_id, user_id=None):
    """
    Store collected feedback for analysis.
    
    Args:
        feedback_data (dict): Submitted feedback.
        session_id (str): Current session ID.
        user_id (str, optional): User ID if available.
    """
    # Store in a database (e.g., feedback table)
    # db_connection.execute("INSERT INTO chatbot_feedback (session_id, user_id, rating, ease_of_use, comments) VALUES (%s, %s, %s, %s, %s)", 
    #                       (session_id, user_id, feedback_data.get('rating'), feedback_data.get('ease_of_use'), feedback_data.get('comments')))
    
    # Optionally, trigger alerts for very low ratings or specific keywords in comments
    if int(feedback_data.get("rating", 3)) <= 2:
        # alert_admin(f"Low feedback score: {feedback_data.get('rating')}, Session: {session_id}")
        pass
    # Perform basic sentiment analysis on comments if desired
    # sentiment = analyze_sentiment(feedback_data.get("comments"))
    # db_connection.execute("UPDATE chatbot_feedback SET comment_sentiment = %s WHERE ...", (sentiment, ...))
    pass
```

## Claude Integration

- **Lead Capture**: Claude can be programmed to identify lead capture triggers based on conversation flow and user intent. Once triggered, Claude can state its intention (e.g., "To help you further, I'd need a few details. Is that okay?") before the UI presents the form. Claude can also provide context for pre-filling form fields.
- **Feedback Collection**: Claude can initiate the feedback request at appropriate junctures (e.g., "Before you go, would you mind answering a couple of quick questions about your experience today?").
- **Handling Form Responses**: Claude can acknowledge form submission (e.g., "Thanks for providing your details! A team member will be in touch shortly." or "Thank you for your feedback! It helps us improve."). If validation fails, Claude can re-prompt or clarify.

## User Flow Examples

### Lead Capture Flow
1.  **User**: "I'm interested in a quote for the 2024 Nissan Rogue SV."
2.  **Chatbot (Claude)**: "I can help with that! The 2024 Nissan Rogue SV is a great choice. To provide you with an accurate quote and check current availability, I'll need a few details."
3.  **UI**: Presents Lead Capture Form (pre-filled with "Nissan Rogue SV" if possible).
4.  **User**: Fills and submits the form.
5.  **System**: Validates data. If valid, pushes to CRM.
6.  **Chatbot (Claude)**: "Thank you, [User Name]! I've received your information. A sales specialist will contact you shortly with the quote for the Nissan Rogue SV. Is there anything else I can assist you with today?"

### Feedback Collection Flow
1.  **User**: "Thanks, that's all I needed."
2.  **Chatbot (Claude)**: "You're welcome! Before you go, would you mind taking a moment to share your feedback about our chat today? It will help us improve our service."
3.  **UI**: Presents Feedback Form.
4.  **User**: Fills and submits the form.
5.  **System**: Stores feedback.
6.  **Chatbot (Claude)**: "Thank you for your valuable feedback! We appreciate you taking the time. Have a great day!"

## Database Schema Updates

### `pending_crm_leads` Table (for CRM push failures)
```sql
CREATE TABLE pending_crm_leads (
    id SERIAL PRIMARY KEY,
    lead_data JSONB NOT NULL,         -- Chatbot collected lead data
    crm_mapped_data JSONB,        -- Data mapped for CRM
    crm_target VARCHAR(50),         -- Target CRM (e.g., 'salesforce')
    last_attempt_timestamp TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    status VARCHAR(20) DEFAULT 'pending', -- pending, failed, success_manual
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `chatbot_feedback` Table
```sql
CREATE TABLE chatbot_feedback (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100),             -- If user is identifiable
    rating INTEGER,                   -- e.g., 1-5
    ease_of_use INTEGER,            -- e.g., 1-5
    comments TEXT,
    comment_sentiment VARCHAR(20),    -- e.g., positive, negative, neutral
    conversation_summary TEXT,      -- Optional summary of the conversation leading to feedback
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Analytics & Reporting

- **Lead Capture Rate**: (Number of leads captured / Number of lead capture opportunities) x 100%.
- **CRM Push Success Rate**: (Number of successful CRM pushes / Total leads captured) x 100%.
- **Feedback Response Rate**: (Number of feedback forms submitted / Number of feedback requests) x 100%.
- **Average Satisfaction Rating (CSAT)**: From feedback ratings.
- **Net Promoter Score (NPS)**: If NPS-style question is included.
- **Sentiment Analysis of Comments**: Track trends in positive/negative feedback.

## Testing Strategy

- **Unit Tests**: Validate lead form data, CRM mapping logic, feedback storage.
- **Integration Tests**: Test end-to-end flow from chatbot trigger to CRM data entry (using mock CRM API), and feedback submission to database storage.
- **User Acceptance Testing (UAT)**: Simulate user conversations to test trigger logic and form presentation.

## Implementation Roadmap

### Phase 1: Lead Capture Core (1 week)
- Implement lead capture trigger logic.
- Develop dynamic lead form presentation.
- Implement data validation service.
- Create `pending_crm_leads` table and local storage fallback.

### Phase 2: CRM Integration (1-2 weeks, depending on CRM complexity)
- Develop CRM mapper for one primary CRM (e.g., Salesforce or a generic webhook).
- Implement CRM API client for pushing leads.
- Test CRM integration thoroughly.

### Phase 3: Feedback Collection (1 week)
- Implement feedback trigger logic.
- Develop feedback form presentation.
- Implement feedback storage and basic analysis (e.g., alerts for low scores).
- Create `chatbot_feedback` table.

### Phase 4: Claude Integration & UI (1 week)
- Integrate Claude to manage lead capture and feedback conversation flows.
- Refine UI for forms and acknowledgments.

### Phase 5: Analytics & Reporting (Ongoing)
- Implement tracking for defined analytics metrics.
- Develop dashboards or reports for lead and feedback data.

### Phase 6: Testing and Optimization (1 week)
- End-to-end testing of all new features.
- Performance tuning and bug fixing.
- Documentation updates.

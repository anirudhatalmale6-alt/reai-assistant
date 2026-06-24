"""Lofty CRM tools for Claude AI."""

from app.services import lofty

TOOLS = [
    {
        "name": "get_crm_leads",
        "description": "Get leads from Lofty CRM. Can filter by status (new, active, hot, warm, cold, closed, etc.). Returns lead names, contact info, scores, and activity data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by lead status (optional). Examples: new, active, hot, warm, cold, closed.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of leads to return (default 20)",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_crm_lead_details",
        "description": "Get detailed information about a specific lead by their ID. Includes full contact info, activities, emails, notes, budget, and property preferences.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "string",
                    "description": "The lead's ID in Lofty CRM",
                },
            },
            "required": ["lead_id"],
        },
    },
    {
        "name": "search_crm_leads",
        "description": "Search for leads in Lofty CRM by name, email, or phone number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - can be a name, email, or phone number",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_lead_activities",
        "description": "Get recent activities for a specific lead (calls, emails, showings, notes, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "string",
                    "description": "The lead's ID in Lofty CRM",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of activities to return (default 10)",
                    "default": 10,
                },
            },
            "required": ["lead_id"],
        },
    },
    {
        "name": "update_crm_lead",
        "description": "Update a lead's information in Lofty CRM. Pass an updates object with the fields to change (status, notes, tags, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "string",
                    "description": "The lead's ID in Lofty CRM",
                },
                "updates": {
                    "type": "object",
                    "description": "Object containing fields to update (e.g., {\"status\": \"hot\", \"notes\": \"Interested in 3BR condo\"})",
                },
            },
            "required": ["lead_id", "updates"],
        },
    },
    {
        "name": "add_lead_note",
        "description": "Add a note to a lead in Lofty CRM. Use this after calls, showings, or meetings to log what was discussed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "string",
                    "description": "The lead's ID in Lofty CRM",
                },
                "note": {
                    "type": "string",
                    "description": "The note content to add",
                },
            },
            "required": ["lead_id", "note"],
        },
    },
    {
        "name": "get_pipeline_summary",
        "description": "Get a summary of the lead pipeline showing total leads, breakdown by status and source, hot leads, and recent leads. Great for daily briefings and quick overviews.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

HANDLERS = {
    "get_crm_leads": lambda params: lofty.get_leads(
        status=params.get("status", ""), limit=params.get("limit", 20)
    ),
    "get_crm_lead_details": lambda params: lofty.get_lead(params["lead_id"]),
    "search_crm_leads": lambda params: lofty.search_leads(
        query=params["query"], limit=params.get("limit", 10)
    ),
    "get_lead_activities": lambda params: lofty.get_lead_activities(
        lead_id=params["lead_id"], limit=params.get("limit", 10)
    ),
    "update_crm_lead": lambda params: lofty.update_lead(
        lead_id=params["lead_id"],
        updates=params["updates"],
    ),
    "add_lead_note": lambda params: lofty.add_lead_note(
        lead_id=params["lead_id"], note=params["note"]
    ),
    "get_pipeline_summary": lambda params: lofty.get_pipeline_summary(),
}

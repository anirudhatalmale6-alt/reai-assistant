from app.services import gmail

TOOLS = [
    {
        "name": "search_emails",
        "description": "Search Gmail for emails matching a query. Use Gmail search syntax (e.g., 'from:john subject:offer', 'is:unread', 'newer_than:2d').",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "max_results": {"type": "integer", "description": "Max emails to return (default 10)", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_email",
        "description": "Read the full content of a specific email by its message ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "The Gmail message ID"},
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email via Gmail. Use this to compose and send emails to clients, leads, or anyone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text"},
                "cc": {"type": "string", "description": "CC email address (optional)", "default": ""},
            },
            "required": ["to", "subject", "body"],
        },
    },
]

HANDLERS = {
    "search_emails": lambda params: gmail.search_emails(params["query"], params.get("max_results", 10)),
    "read_email": lambda params: gmail.read_email(params["message_id"]),
    "send_email": lambda params: gmail.send_email(params["to"], params["subject"], params["body"], params.get("cc", "")),
}

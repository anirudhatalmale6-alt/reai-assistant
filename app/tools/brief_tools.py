"""Daily brief and overview tools for Claude AI."""

from app.services import daily_brief

TOOLS = [
    {
        "name": "generate_daily_brief",
        "description": "Generate a comprehensive daily briefing including today's calendar, unread emails, important messages, and lead priorities. Use this when the user asks for their morning brief, daily summary, or 'what do I need to know today'. Present the results in a clear, organized format with sections.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

HANDLERS = {
    "generate_daily_brief": lambda params: daily_brief.generate_daily_brief(),
}

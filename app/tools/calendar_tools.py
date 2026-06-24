from app.services import calendar

TOOLS = [
    {
        "name": "list_calendar_events",
        "description": "List upcoming calendar events. Shows meetings, appointments, showings, etc. Can specify a start date and number of days to look ahead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format. Defaults to today if not provided.",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days to look ahead (default 1)",
                    "default": 1,
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a new calendar event (meeting, showing, appointment, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start datetime in ISO format (e.g., 2026-04-20T14:00:00)"},
                "end": {"type": "string", "description": "End datetime in ISO format (e.g., 2026-04-20T15:00:00)"},
                "description": {"type": "string", "description": "Event description/notes", "default": ""},
                "location": {"type": "string", "description": "Event location/address", "default": ""},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses",
                    "default": [],
                },
            },
            "required": ["summary", "start", "end"],
        },
    },
    {
        "name": "find_free_slots",
        "description": "Find available time slots on a given date for scheduling meetings or showings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date to check (YYYY-MM-DD)"},
                "duration_minutes": {
                    "type": "integer",
                    "description": "Duration needed in minutes",
                    "default": 60,
                },
            },
            "required": ["date"],
        },
    },
]


def _list_calendar_events(params):
    from datetime import datetime, timedelta

    date = params.get("date", "")
    days = params.get("days", 1)

    if date:
        time_min = f"{date}T00:00:00"
    else:
        time_min = datetime.now().strftime("%Y-%m-%dT00:00:00")
        date = datetime.now().strftime("%Y-%m-%d")

    end_date = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    time_max = f"{end_date}T00:00:00"

    return calendar.list_events(time_min=time_min, time_max=time_max, max_results=50)


HANDLERS = {
    "list_calendar_events": _list_calendar_events,
    "create_calendar_event": lambda params: calendar.create_event(
        params["summary"], params["start"], params["end"],
        params.get("description", ""), params.get("location", ""), params.get("attendees", [])
    ),
    "find_free_slots": lambda params: calendar.find_free_slots(
        params["date"], params.get("duration_minutes", 60)
    ),
}

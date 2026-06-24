"""Dashboard API endpoint for stats cards."""

from fastapi import APIRouter
from app.services.daily_brief import generate_daily_brief
from app.services.google_auth import get_credentials

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard():
    """Get dashboard data for stats cards."""
    creds = get_credentials()
    google_connected = creds is not None

    data = {
        "google_connected": google_connected,
        "stats": {
            "unread_emails": 0,
            "today_events": 0,
            "tomorrow_events": 0,
        },
    }

    if google_connected:
        try:
            brief = generate_daily_brief()
            data["stats"]["unread_emails"] = brief.get("inbox", {}).get("unread_count", 0)
            data["stats"]["today_events"] = brief.get("calendar", {}).get("today_count", 0)
            data["stats"]["tomorrow_events"] = brief.get("calendar", {}).get("tomorrow_count", 0)
        except Exception:
            pass

    return data

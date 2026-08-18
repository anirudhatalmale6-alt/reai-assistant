"""Dashboard API endpoint for stats cards."""

import logging
from datetime import date, timedelta

from fastapi import APIRouter

from app.services import calendar as calendar_service
from app.services.daily_brief import generate_daily_brief
from app.services.google_auth import get_credentials

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/dashboard")
async def get_dashboard():
    """Counts for the three tiles at the top of the app.

    generate_daily_brief() returns a flat dict - unread_count, today_events (a
    list of events, not a count) - and carries nothing about tomorrow. This used
    to read brief["inbox"]["unread_count"] and brief["calendar"]["today_count"],
    neither of which has ever existed, so every tile reported 0 while the inbox
    actually held 50 unread. The old bare `except: pass` then hid the fact that
    anything was wrong at all.
    """
    creds = get_credentials()
    google_connected = creds is not None

    stats = {"unread_emails": 0, "today_events": 0, "tomorrow_events": 0}
    errors = []

    if google_connected:
        try:
            brief = generate_daily_brief()
            stats["unread_emails"] = int(brief.get("unread_count") or 0)
            today = brief.get("today_events") or []
            stats["today_events"] = len(today) if isinstance(today, list) else int(today or 0)
        except Exception as exc:
            logger.exception("dashboard: daily brief failed")
            errors.append(f"inbox/today: {exc}")

        try:
            tomorrow = (date.today() + timedelta(days=1)).isoformat()
            stats["tomorrow_events"] = len(
                calendar_service.list_events(date=tomorrow, days=1) or []
            )
        except Exception as exc:
            logger.exception("dashboard: tomorrow's calendar failed")
            errors.append(f"tomorrow: {exc}")

    data = {"google_connected": google_connected, "stats": stats}
    if errors:
        # Surfaced rather than swallowed - a tile stuck on zero should be
        # distinguishable from a tile that is genuinely zero.
        data["errors"] = errors
    return data

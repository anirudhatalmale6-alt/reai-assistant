"""
Daily briefing aggregator.

Pulls data from Gmail, Calendar, and Lofty CRM to build a
morning briefing summary for the real estate agent.
"""

import logging
from datetime import datetime

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TIMEZONE = "America/Toronto"
TZ = ZoneInfo(TIMEZONE)


def generate_daily_brief() -> dict:
    """
    Generate a comprehensive morning briefing.

    Aggregates:
    - Unread email count and recent important emails
    - Today's calendar events
    - Upcoming tasks / follow-ups
    - Hot leads from Lofty CRM (if connected)

    Returns:
        Dict with keys: date, unread_count, important_emails,
        today_events, upcoming_tasks, hot_leads, summary
    """
    today = datetime.now(TZ)
    today_str = today.strftime("%Y-%m-%d")

    brief = {
        "date": today_str,
        "day_of_week": today.strftime("%A"),
        "unread_count": 0,
        "important_emails": [],
        "today_events": [],
        "upcoming_tasks": [],
        "hot_leads": [],
        "summary": "",
    }

    # --- Gmail: unread count and important emails ---
    try:
        from app.services.gmail import search_emails

        unread = search_emails("is:unread", max_results=50)
        brief["unread_count"] = len(unread)

        # Get important/starred unread emails
        important = search_emails("is:unread is:important", max_results=5)
        brief["important_emails"] = [
            {
                "subject": e.get("subject", ""),
                "from": e.get("from", ""),
                "snippet": e.get("snippet", ""),
            }
            for e in important
        ]
    except Exception as e:
        logger.warning("Failed to fetch Gmail data for daily brief: %s", e)
        brief["important_emails"] = [{"error": f"Gmail unavailable: {e}"}]

    # --- Calendar: today's events ---
    try:
        from app.services.calendar import list_events

        events = list_events(date=today_str, days=1)
        brief["today_events"] = [
            {
                "summary": ev.get("summary", ""),
                "start": ev.get("start", ""),
                "end": ev.get("end", ""),
                "location": ev.get("location", ""),
            }
            for ev in events
        ]
    except Exception as e:
        logger.warning("Failed to fetch Calendar data for daily brief: %s", e)
        brief["today_events"] = [{"error": f"Calendar unavailable: {e}"}]

    # --- Lofty CRM: hot leads and tasks ---
    try:
        from app.services.lofty import get_hot_leads, get_upcoming_tasks

        brief["hot_leads"] = get_hot_leads()
        brief["upcoming_tasks"] = get_upcoming_tasks()
    except ImportError:
        logger.info("Lofty CRM service not yet implemented")
        brief["hot_leads"] = []
        brief["upcoming_tasks"] = []
    except Exception as e:
        logger.warning("Failed to fetch Lofty CRM data for daily brief: %s", e)
        brief["hot_leads"] = [{"error": f"Lofty CRM unavailable: {e}"}]
        brief["upcoming_tasks"] = [{"error": f"Lofty CRM unavailable: {e}"}]

    # --- Build summary text ---
    summary_parts = [
        f"Good morning! Here's your briefing for {today.strftime('%A, %B %d, %Y')}.",
    ]

    if brief["unread_count"] > 0:
        summary_parts.append(
            f"You have {brief['unread_count']} unread email(s)."
        )
    else:
        summary_parts.append("Your inbox is clear - no unread emails.")

    event_count = len([e for e in brief["today_events"] if "error" not in e])
    if event_count > 0:
        summary_parts.append(
            f"You have {event_count} event(s) on your calendar today."
        )
    else:
        summary_parts.append("No events on your calendar today.")

    lead_count = len([l for l in brief["hot_leads"] if "error" not in l])
    if lead_count > 0:
        summary_parts.append(
            f"You have {lead_count} hot lead(s) requiring attention."
        )

    task_count = len([t for t in brief["upcoming_tasks"] if "error" not in t])
    if task_count > 0:
        summary_parts.append(
            f"You have {task_count} upcoming task(s) / follow-up(s)."
        )

    brief["summary"] = " ".join(summary_parts)

    return brief

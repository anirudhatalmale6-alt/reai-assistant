"""
Google Calendar API service for listing, creating events and finding free slots.
"""

import logging
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo
from googleapiclient.discovery import build

from app.services.google_auth import get_credentials

logger = logging.getLogger(__name__)

TIMEZONE = "America/Toronto"
TZ = ZoneInfo(TIMEZONE)


def _get_calendar_service():
    """Build and return a Google Calendar API service instance."""
    creds = get_credentials()
    if not creds:
        raise RuntimeError(
            "Google credentials not found. Please connect your Google account first."
        )
    return build("calendar", "v3", credentials=creds)


def list_events(
    date: str = "",
    days: int = 1,
    time_min: str = "",
    time_max: str = "",
    max_results: int = 50,
) -> list[dict]:
    """
    List calendar events for a date range.

    Can be called either with date/days for simple usage, or with
    explicit time_min/time_max ISO strings for precise control.

    Args:
        date: Start date in YYYY-MM-DD format (defaults to today)
        days: Number of days to look ahead (default 1)
        time_min: Explicit start time in ISO format (overrides date)
        time_max: Explicit end time in ISO format (overrides days)
        max_results: Maximum number of events to return (default 50)

    Returns:
        List of dicts with keys: id, summary, start, end, location, description
    """
    service = _get_calendar_service()

    # If explicit time_min/time_max provided, use them directly
    if time_min and time_max:
        # Ensure timezone info is attached
        if "T" in time_min and "+" not in time_min and "Z" not in time_min and "-" not in time_min.split("T")[1]:
            time_min = time_min + TZ.tzname(datetime.now(TZ))
        if "T" in time_max and "+" not in time_max and "Z" not in time_max and "-" not in time_max.split("T")[1]:
            time_max = time_max + TZ.tzname(datetime.now(TZ))
    else:
        # Build from date/days
        if date:
            try:
                start_dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=TZ)
            except ValueError:
                start_dt = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_dt = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)

        end_dt = start_dt + timedelta(days=days)

        time_min = start_dt.isoformat()
        time_max = end_dt.isoformat()

    try:
        results = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                timeZone=TIMEZONE,
                maxResults=max_results,
            )
            .execute()
        )
    except Exception as e:
        logger.error("Failed to list calendar events: %s", e)
        return []

    events = []
    for event in results.get("items", []):
        start = event.get("start", {})
        end = event.get("end", {})

        events.append({
            "id": event.get("id", ""),
            "summary": event.get("summary", "(no title)"),
            "start": start.get("dateTime", start.get("date", "")),
            "end": end.get("dateTime", end.get("date", "")),
            "location": event.get("location", ""),
            "description": event.get("description", ""),
        })

    return events


def create_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: str | list = "",
) -> dict:
    """
    Create a calendar event.

    Args:
        summary: Event title
        start: Start time in ISO 8601 format (e.g. "2026-06-05T10:00:00")
        end: End time in ISO 8601 format
        description: Event description (optional)
        location: Event location (optional)
        attendees: Email addresses - comma-separated string or list (optional)

    Returns:
        Dict with event details: id, summary, start, end, link
    """
    service = _get_calendar_service()

    # Ensure timezone is attached if not present
    if "T" in start and "+" not in start and "Z" not in start:
        start = start + f"-04:00"  # Eastern Time offset (approximate)
    if "T" in end and "+" not in end and "Z" not in end:
        end = end + f"-04:00"

    event_body = {
        "summary": summary,
        "start": {"dateTime": start, "timeZone": TIMEZONE},
        "end": {"dateTime": end, "timeZone": TIMEZONE},
    }

    if description:
        event_body["description"] = description
    if location:
        event_body["location"] = location
    if attendees:
        if isinstance(attendees, str):
            attendee_list = [e.strip() for e in attendees.split(",") if e.strip()]
        else:
            attendee_list = [e.strip() if isinstance(e, str) else e for e in attendees]
        event_body["attendees"] = [
            {"email": email} for email in attendee_list if email
        ]

    try:
        created = (
            service.events()
            .insert(calendarId="primary", body=event_body, sendUpdates="all")
            .execute()
        )

        logger.info("Calendar event created: %s", created.get("id"))
        return {
            "id": created.get("id", ""),
            "summary": created.get("summary", ""),
            "start": created.get("start", {}).get("dateTime", ""),
            "end": created.get("end", {}).get("dateTime", ""),
            "link": created.get("htmlLink", ""),
        }
    except Exception as e:
        logger.error("Failed to create calendar event: %s", e)
        return {"error": str(e)}


def find_free_slots(date: str, duration_minutes: int = 60) -> list[dict]:
    """
    Find available time slots on a given date.

    Checks calendar events between 9 AM and 6 PM and returns
    slots that are free and at least `duration_minutes` long.

    Args:
        date: Date in YYYY-MM-DD format
        duration_minutes: Minimum slot duration in minutes (default 60)

    Returns:
        List of dicts with keys: start, end, duration_minutes
    """
    events = list_events(date=date, days=1)

    try:
        day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=TZ)
    except ValueError:
        day = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)

    work_start = day.replace(hour=9, minute=0, second=0, microsecond=0)
    work_end = day.replace(hour=18, minute=0, second=0, microsecond=0)

    # Parse event times into (start, end) tuples
    busy_slots = []
    for event in events:
        try:
            evt_start = _parse_datetime(event["start"])
            evt_end = _parse_datetime(event["end"])
            if evt_start and evt_end:
                busy_slots.append((evt_start, evt_end))
        except Exception:
            continue

    # Sort busy slots by start time
    busy_slots.sort(key=lambda x: x[0])

    # Find gaps
    free_slots = []
    current = work_start

    for busy_start, busy_end in busy_slots:
        # Clamp to work hours
        if busy_end <= work_start:
            continue
        if busy_start >= work_end:
            break

        busy_start = max(busy_start, work_start)
        busy_end = min(busy_end, work_end)

        if current < busy_start:
            gap_minutes = int((busy_start - current).total_seconds() / 60)
            if gap_minutes >= duration_minutes:
                free_slots.append({
                    "start": current.strftime("%Y-%m-%dT%H:%M:%S"),
                    "end": busy_start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "duration_minutes": gap_minutes,
                })

        current = max(current, busy_end)

    # Check remaining time after last event
    if current < work_end:
        gap_minutes = int((work_end - current).total_seconds() / 60)
        if gap_minutes >= duration_minutes:
            free_slots.append({
                "start": current.strftime("%Y-%m-%dT%H:%M:%S"),
                "end": work_end.strftime("%Y-%m-%dT%H:%M:%S"),
                "duration_minutes": gap_minutes,
            })

    return free_slots


def _parse_datetime(dt_string: str) -> datetime | None:
    """Parse a datetime string from Google Calendar into a timezone-aware datetime."""
    if not dt_string:
        return None

    # Try ISO format with timezone offset (e.g. 2026-06-05T10:00:00-04:00)
    try:
        return datetime.fromisoformat(dt_string).astimezone(TZ)
    except (ValueError, TypeError):
        pass

    # Try date-only format (all-day events)
    try:
        return datetime.strptime(dt_string, "%Y-%m-%d").replace(tzinfo=TZ)
    except (ValueError, TypeError):
        pass

    return None

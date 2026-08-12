"""Lofty CRM (formerly Chime) API integration service."""

import requests
from app.config import settings

BASE_URL = "https://api.lofty.com/v1.0"


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 REAI/1.0"


def _headers():
    from app.services.lofty_auth import get_access_token
    oauth_token = get_access_token()
    if oauth_token:
        return {
            "Authorization": f"Bearer {oauth_token}",
            "Content-Type": "application/json",
            "User-Agent": _UA,
        }
    if settings.LOFTY_API_KEY:
        return {
            "Authorization": f"token {settings.LOFTY_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": _UA,
        }
    raise ValueError(
        "Lofty CRM is not connected yet. Please click 'Connect Lofty' in the top bar, "
        "or provide an API key from Lofty CRM Settings > Integrations > API."
    )


def get_leads(status: str = "", limit: int = 20, sort_by: str = "") -> list[dict]:
    """Get leads from Lofty CRM."""
    params = {"limit": limit}
    if sort_by:
        params["sort"] = sort_by
    if status:
        params["status"] = status

    try:
        resp = requests.get(f"{BASE_URL}/leads", headers=_headers(), params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        leads = data.get("leads", data.get("data", []))
        return [
            {
                "id": lead.get("leadId", lead.get("id", "")),
                "name": f"{lead.get('firstName', lead.get('first_name', ''))} {lead.get('lastName', lead.get('last_name', ''))}".strip(),
                "email": (lead.get("emails") or [""])[0] if isinstance(lead.get("emails"), list) else lead.get("email", ""),
                "phone": (lead.get("phones") or [""])[0] if isinstance(lead.get("phones"), list) else lead.get("phone", ""),
                "status": lead.get("stage", lead.get("status", "")),
                "source": lead.get("source", ""),
                "stage": lead.get("stage", ""),
                "score": lead.get("score", ""),
                "last_activity": lead.get("lastUpdateTime", lead.get("last_activity_at", "")),
                "created_at": lead.get("createTime", lead.get("created_at", "")),
                "tags": lead.get("tags", []),
                "assigned_to": lead.get("assignedUser", lead.get("assigned_to", "")),
            }
            for lead in leads
        ]
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            raise ValueError("Lofty API key is invalid or expired. Please update it in settings.")
        raise ValueError(f"Lofty API error: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.ConnectionError:
        raise ValueError("Could not connect to Lofty CRM. Please check your internet connection.")


def get_lead(lead_id: str) -> dict:
    """Get details for a specific lead.

    Lofty answers with {"lead": {...}} and camelCase keys - the snake_case
    guesses this used to make silently returned an empty record for every lead.
    """
    try:
        resp = requests.get(f"{BASE_URL}/leads/{lead_id}", headers=_headers(), timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        lead = payload.get("lead") or payload.get("data") or payload
        if isinstance(lead, list):
            lead = lead[0] if lead else {}
        inquiry = lead.get("leadInquiry") or {}
        return {
            "id": lead.get("leadId", ""),
            "name": f"{lead.get('firstName') or ''} {lead.get('lastName') or ''}".strip(),
            "email": (lead.get("emails") or [""])[0],
            "phone": (lead.get("phones") or [""])[0],
            "status": lead.get("stage", ""),
            "source": lead.get("source", ""),
            "stage": lead.get("stage", ""),
            "score": lead.get("score", ""),
            "last_activity": lead.get("lastUpdateTime", ""),
            "created_at": lead.get("createTime", ""),
            "tags": [t.get("tagName") for t in (lead.get("tags") or []) if isinstance(t, dict)],
            "note": lead.get("note", ""),
            "address": ", ".join(p for p in (lead.get("streetAddress"), lead.get("city"),
                                             lead.get("state"), lead.get("zipCode")) if p),
            "budget_min": inquiry.get("priceMin", ""),
            "budget_max": inquiry.get("priceMax", ""),
            "property_type": ", ".join(inquiry.get("propertyType") or []),
            "assigned_to": lead.get("assignedUser", ""),
            "emails": lead.get("emails", []),
            "phones": lead.get("phones", []),
            "unsubscribed": lead.get("unsubscription", False),
        }
    except requests.exceptions.HTTPError as e:
        raise ValueError(f"Lofty API error: {e.response.status_code}")


def search_leads(query: str, limit: int = 10) -> list[dict]:
    """Search leads by name, email, or phone.

    There is no search endpoint - /leads/search resolves to /leads/{leadId} and
    400s on "search". Lofty only filters server-side on email, so an email-ish
    query goes to the API and anything else is matched against the local contact
    index built for segmenting.
    """
    def shape(lead: dict) -> dict:
        return {
            "id": lead.get("leadId", ""),
            "name": f"{lead.get('firstName') or ''} {lead.get('lastName') or ''}".strip(),
            "email": (lead.get("emails") or [""])[0],
            "phone": (lead.get("phones") or [""])[0],
            "status": lead.get("stage", ""),
            "source": lead.get("source", ""),
            "stage": lead.get("stage", ""),
            "score": lead.get("score", ""),
            "last_activity": lead.get("lastUpdateTime", ""),
            "assigned_to": lead.get("assignedUser", ""),
        }

    term = (query or "").strip()
    if not term:
        return []

    if "@" in term:
        try:
            resp = requests.get(f"{BASE_URL}/leads", headers=_headers(),
                                params={"email": term, "limit": min(limit, 100)}, timeout=20)
            resp.raise_for_status()
            return [shape(lead) for lead in (resp.json().get("leads") or [])][:limit]
        except requests.exceptions.HTTPError as e:
            raise ValueError(f"Lofty search error: {e.response.status_code}")

    # Name or phone: use the cached index, then pull full records for the hits.
    from app.services import segments
    digits = "".join(ch for ch in term if ch.isdigit())
    needle = term.lower()
    hits = []
    for contact in segments.load_index()["contacts"]:
        name = f"{contact['first']} {contact['last']}".strip().lower()
        if needle in name or (len(digits) >= 7 and digits in contact.get("phone", "")):
            hits.append(contact)
        if len(hits) >= limit:
            break

    results = []
    for contact in hits:
        try:
            results.append(get_lead(str(contact["id"])))
        except ValueError:
            results.append({"id": contact["id"],
                            "name": f"{contact['first']} {contact['last']}".strip(),
                            "email": contact["email"], "stage": contact["stage"],
                            "source": contact["source"], "assigned_to": contact["owner"]})
    return results


def get_lead_activities(lead_id: str, limit: int = 10) -> list[dict]:
    """Get recent activities for a lead."""
    try:
        resp = requests.get(
            f"{BASE_URL}/leads/{lead_id}/activities",
            headers=_headers(),
            params={"limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        activities = data.get("data", data.get("activities", []))
        return [
            {
                "type": a.get("type", ""),
                "description": a.get("description", a.get("content", "")),
                "created_at": a.get("created_at", ""),
                "agent": a.get("agent_name", ""),
            }
            for a in activities
        ]
    except requests.exceptions.HTTPError:
        return []


def update_lead(lead_id: str, updates: dict) -> dict:
    """Update a lead's information in the CRM.

    Two traps found the hard way:
      - PATCH is not supported at all (405). PUT is the verb, and a partial body
        only touches the fields it names.
      - A refused write still answers HTTP 200, with the real outcome in
        status.code / status.msg (e.g. 300011 "This email address already exists
        as a lead"). Checking the HTTP code alone reports success on a no-op.

    Writable: firstName, lastName, stage, source, emails (list of strings),
    phones (list of strings), tags (list of strings - replaces the whole list,
    and an empty list is ignored, so tags cannot be cleared, only replaced).
    """
    try:
        resp = requests.put(
            f"{BASE_URL}/leads/{lead_id}",
            headers=_headers(),
            json=updates,
            timeout=20,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise ValueError(f"Failed to update lead: {e.response.status_code} - {e.response.text[:200]}")

    try:
        status = (resp.json().get("status") or {})
    except ValueError:
        status = {}
    code, message = status.get("code"), status.get("msg")
    if code and code != 200:
        raise ValueError(f"Lofty refused the update ({code}): {message}")
    return {"status": "updated", "lead_id": lead_id, "fields": sorted(updates)}


def add_lead_note(lead_id: str, note: str) -> dict:
    """Add a note to a lead."""
    try:
        resp = requests.post(
            f"{BASE_URL}/leads/{lead_id}/notes",
            headers=_headers(),
            json={"content": note},
            timeout=15,
        )
        resp.raise_for_status()
        return {"status": "note_added", "lead_id": lead_id}
    except requests.exceptions.HTTPError as e:
        raise ValueError(f"Failed to add note: {e.response.status_code}")


def get_pipeline_summary() -> dict:
    """Get a summary of the lead pipeline."""
    try:
        all_leads = get_leads(limit=100)
        summary = {
            "total_leads": len(all_leads),
            "by_status": {},
            "by_source": {},
            "recent_leads": [],
            "hot_leads": [],
        }

        for lead in all_leads:
            status = lead.get("status", "unknown")
            source = lead.get("source", "unknown")
            summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
            summary["by_source"][source] = summary["by_source"].get(source, 0) + 1

        summary["recent_leads"] = all_leads[:5]
        summary["hot_leads"] = [
            lead for lead in all_leads
            if lead.get("score") and (isinstance(lead["score"], (int, float)) and lead["score"] >= 70)
        ][:5]

        return summary
    except Exception as e:
        raise ValueError(f"Failed to get pipeline summary: {str(e)}")

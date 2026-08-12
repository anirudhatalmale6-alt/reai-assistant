"""CRM segmentation for bulk sends (Deal of the Week and similar).

Lofty's API only filters server-side on stage / source / email substring, and
caps pages at 100, so the whole contact list is scanned once and cached
locally. Everything else - tags, owner, lead type, city - is filtered here.

Nothing in this module sends email. It selects and counts people, and the
caller is responsible for the approval step.
"""
import json
import re
import time
from pathlib import Path

import requests

from app.services.lofty import BASE_URL, _headers

CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "crm_index.json"
CACHE_MAX_AGE = 12 * 3600  # a working day; contacts don't churn faster than that
PAGE_SIZE = 100            # Lofty's hard maximum
DAILY_SEND_CAP = 5000      # what his Lofty plan allows per day


# --------------------------------------------------------------------------- #
# building / loading the local index
# --------------------------------------------------------------------------- #
# Placeholder addresses minted by lead vendors (the old kvCORE/KV Leads import
# left 937 of them). They look valid and are not real inboxes - sending to them
# means hundreds of hard bounces in one go, which is how a domain gets blacklisted.
BLOCKED_DOMAINS = {"kvleads.com", "chimeleads.com", "loftyleads.com", "example.com"}

# Near-misses of real providers. These bounce too, so they are excluded until
# somebody corrects the spelling in the CRM.
TYPO_DOMAINS = {
    "gmial.com", "gmai.com", "gmail.co", "gmail.con", "gmail.cm", "gnail.com", "gmaill.com",
    "hotmial.com", "hotmail.co", "hotmail.con", "hotmai.com", "hotmial.co",
    "yaho.com", "yahoo.co", "yahooo.com", "yahoo.con", "ymail.co",
    "ouctlook.com", "outlok.com", "outlook.co", "outloo.com", "otlook.com",
    "icloud.co", "iclould.com",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def email_problem(address: str) -> str:
    """Why this address can't be mailed, or "" if it's fine."""
    value = (address or "").strip()
    if not value:
        return "missing"
    if not EMAIL_RE.match(value):
        return "malformed"
    domain = value.rsplit("@", 1)[-1].lower()
    if domain in BLOCKED_DOMAINS:
        return "placeholder address from a lead vendor, not a real inbox"
    if domain in TYPO_DOMAINS:
        return f"misspelled domain ({domain})"
    return ""


# Lofty's AI assistant flags people who told it to stop contacting them. That is
# a do-not-call marker rather than an email unsubscribe, but somebody who has
# said "leave me alone" does not belong in a bulk send either.
DNC_TAGS = {"ai: dnc", "dnc", "do not contact", "do not call"}


def _is_emailable(lead: dict) -> bool:
    """Whether we may legally and technically email this contact.

    Excluding these is not optional: emailing an unsubscribe breaches CASL, and
    bouncing off fake vendor addresses wrecks sender reputation. Enforced here so
    no caller can forget.
    """
    if lead.get("cannotEmail") or lead.get("unsubscription"):
        return False
    if any(name.strip().lower() in DNC_TAGS for name in _tag_names(lead)):
        return False
    return not email_problem(_first_email(lead))


def _first_email(lead: dict) -> str:
    emails = lead.get("emails") or []
    for entry in emails:
        if isinstance(entry, str) and "@" in entry:
            return entry.strip()
        if isinstance(entry, dict):
            value = (entry.get("email") or entry.get("value") or "").strip()
            if "@" in value:
                return value
    return ""


def _tag_names(lead: dict) -> list[str]:
    names = []
    for tag in lead.get("tags") or []:
        name = tag.get("tagName") or tag.get("name")
        if name:
            names.append(str(name))
    return names


def _slim(lead: dict) -> dict:
    """Keep only what segmenting and merge fields need."""
    return {
        "id": lead.get("leadId"),
        "first": (lead.get("firstName") or "").strip(),
        "last": (lead.get("lastName") or "").strip(),
        "email": _first_email(lead),
        "phone": next((str(p) for p in (lead.get("phones") or []) if p), ""),
        "stage": lead.get("stage") or "(no stage)",
        "source": lead.get("source") or "(no source)",
        "tags": _tag_names(lead),
        "owner": lead.get("assignedUser") or "(unassigned)",
        "city": lead.get("city") or "",
        "types": [str(t) for t in (lead.get("leadTypes") or []) if t is not None],
        "emailable": _is_emailable(lead),
    }


def refresh_index() -> dict:
    """Scan every contact from Lofty and cache a slim local copy."""
    headers = _headers()
    contacts: list[dict] = []
    scroll = None
    total = 0

    while True:
        params = {"limit": PAGE_SIZE}
        if scroll:
            params["scrollId"] = scroll
        resp = requests.get(f"{BASE_URL}/leads", headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        leads = payload.get("leads") or []
        meta = payload.get("_metadata") or {}
        total = meta.get("total", total)
        scroll = meta.get("scrollId")
        if not leads:
            break
        contacts.extend(_slim(lead) for lead in leads)
        if len(contacts) >= total or not scroll:
            break

    index = {"built_at": int(time.time()), "total": total, "contacts": contacts}
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(index))
    return index


def load_index(max_age: int = CACHE_MAX_AGE) -> dict:
    if CACHE_FILE.exists():
        try:
            index = json.loads(CACHE_FILE.read_text())
            if time.time() - index.get("built_at", 0) < max_age:
                return index
        except (ValueError, OSError):
            pass
    return refresh_index()


# --------------------------------------------------------------------------- #
# inventory + selection
# --------------------------------------------------------------------------- #
def _tally(contacts: list[dict], key) -> list[dict]:
    totals: dict[str, list[int]] = {}
    for contact in contacts:
        values = key(contact)
        for value in (values if isinstance(values, list) else [values]):
            if not value:
                continue
            row = totals.setdefault(str(value), [0, 0])
            row[0] += 1
            row[1] += bool(contact["emailable"])
    rows = [{"value": v, "contacts": c, "emailable": e} for v, (c, e) in totals.items()]
    return sorted(rows, key=lambda r: -r["emailable"])


def inventory(refresh: bool = False) -> dict:
    """What segments actually exist, with how many of each can be emailed."""
    index = refresh_index() if refresh else load_index()
    contacts = index["contacts"]
    return {
        "total_contacts": len(contacts),
        "emailable": sum(1 for c in contacts if c["emailable"]),
        "not_emailable": sum(1 for c in contacts if not c["emailable"]),
        "built_at": index["built_at"],
        "stages": _tally(contacts, lambda c: c["stage"]),
        "sources": _tally(contacts, lambda c: c["source"]),
        "tags": _tally(contacts, lambda c: c["tags"])[:30],
        "owners": _tally(contacts, lambda c: c["owner"]),
        "cities": _tally(contacts, lambda c: c["city"])[:20],
    }


def select(stages: list[str] | None = None, sources: list[str] | None = None,
           tags: list[str] | None = None, owner: str | None = None,
           exclude_stages: list[str] | None = None, cities: list[str] | None = None,
           limit: int | None = None) -> dict:
    """Pick recipients. Non-emailable contacts can never be included.

    Filters are OR within a category and AND across categories, which is how
    people describe segments out loud ("nurture or warm, from open houses").
    """
    index = load_index()
    lower = lambda values: {v.strip().lower() for v in values or []}  # noqa: E731
    want_stages, want_sources = lower(stages), lower(sources)
    want_tags, want_cities = lower(tags), lower(cities)
    skip_stages = lower(exclude_stages)
    want_owner = (owner or "").strip().lower()

    chosen = []
    for contact in index["contacts"]:
        if not contact["emailable"]:
            continue
        if want_stages and contact["stage"].lower() not in want_stages:
            continue
        if skip_stages and contact["stage"].lower() in skip_stages:
            continue
        if want_sources and contact["source"].lower() not in want_sources:
            continue
        if want_cities and contact["city"].lower() not in want_cities:
            continue
        if want_tags and not ({t.lower() for t in contact["tags"]} & want_tags):
            continue
        if want_owner and want_owner not in contact["owner"].lower():
            continue
        chosen.append(contact)

    truncated = bool(limit) and len(chosen) > limit
    if truncated:
        chosen = chosen[:limit]

    warnings = []
    if len(chosen) > DAILY_SEND_CAP:
        warnings.append(
            f"{len(chosen)} recipients is over the {DAILY_SEND_CAP}/day your Lofty plan "
            f"allows - split this across two days or narrow the segment."
        )
    if truncated:
        warnings.append(f"List was cut to the {limit} you asked for.")
    if not chosen:
        warnings.append("No contacts matched. Check the segment names against the inventory.")

    return {
        "count": len(chosen),
        "recipients": chosen,
        "sample": [f"{c['first']} {c['last']} <{c['email']}>".strip() for c in chosen[:5]],
        "warnings": warnings,
    }

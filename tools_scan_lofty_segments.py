"""One-off read-only audit of the Lofty database.

Builds the real segment inventory (stage / source / lead type / tag / city) and
counts how many contacts in each are actually emailable, so Deal of the Week
can offer segments that exist rather than ones we guessed at.

Read-only: GET /leads only. Writes a JSON summary next to this file.
"""
import collections
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

OUT = Path(__file__).resolve().parent / "data" / "lofty_segment_audit.json"


def emailable(lead: dict) -> bool:
    """A contact we may legally and technically email."""
    if lead.get("cannotEmail"):
        return False
    if lead.get("unsubscription"):
        return False
    return bool(lead.get("emails"))


def main() -> None:
    headers = _headers()
    counters = {k: collections.Counter() for k in
                ("stage", "source", "leadType", "tag", "city", "assignedUser", "pondName")}
    mailable = {k: collections.Counter() for k in counters}
    total = seen = emailable_total = 0
    scroll = None

    while True:
        params = {"limit": 100}
        if scroll:
            params["scrollId"] = scroll
        resp = requests.get(f"{BASE_URL}/leads", headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"stopped: {resp.status_code} {resp.text[:200]}", flush=True)
            break
        payload = resp.json()
        leads = payload.get("leads") or []
        meta = payload.get("_metadata") or {}
        total = meta.get("total", total)
        scroll = meta.get("scrollId")
        if not leads:
            break

        for lead in leads:
            seen += 1
            ok = emailable(lead)
            emailable_total += ok

            buckets = {
                "stage": [lead.get("stage") or "(no stage)"],
                "source": [lead.get("source") or "(no source)"],
                "leadType": (lead.get("leadTypes") or [lead.get("leadType")] or []),
                "tag": [t.get("tagName") or t.get("name") or f"tag:{t.get('tagId')}"
                        for t in (lead.get("tags") or [])],
                "city": [lead.get("city") or "(no city)"],
                "assignedUser": [lead.get("assignedUser") or "(unassigned)"],
                "pondName": [lead.get("pondName") or "(no pond)"],
            }
            for key, values in buckets.items():
                for value in values:
                    if value in (None, ""):
                        continue
                    counters[key][str(value)] += 1
                    if ok:
                        mailable[key][str(value)] += 1

        print(f"scanned {seen}/{total}", flush=True)
        if seen >= total or not scroll:
            break
        time.sleep(0.2)  # be polite to their API

    summary = {
        "total_contacts": total,
        "scanned": seen,
        "emailable": emailable_total,
        "not_emailable": seen - emailable_total,
        "breakdown": {
            key: [
                {"value": value, "contacts": count, "emailable": mailable[key][value]}
                for value, count in counters[key].most_common(40)
            ]
            for key in counters
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {OUT}")
    print(f"TOTAL {seen} | EMAILABLE {emailable_total} | BLOCKED {seen - emailable_total}")


if __name__ == "__main__":
    main()

"""PUT is the verb Lofty accepts. Now find out which FIELDS it will honour.

Demo record only (Chime Guide). Restores the name first - the verb probe left it
as "GuideProbe" - then tests one field at a time, reading the record back after
each write so we know what really landed rather than trusting a 200.
"""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

LEAD_ID = "1127720690818985"
OUT = Path(__file__).resolve().parent / "data" / "lofty_put_probe.json"


def read():
    resp = requests.get(f"{BASE_URL}/leads/{LEAD_ID}", headers=_headers(), timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("lead", payload.get("data", payload))


def put(body):
    resp = requests.put(f"{BASE_URL}/leads/{LEAD_ID}", headers=_headers(),
                        json=body, timeout=20)
    return resp


def snapshot(lead):
    return {
        "firstName": lead.get("firstName"),
        "lastName": lead.get("lastName"),
        "stage": lead.get("stage"),
        "tags": lead.get("tags"),
        "emails": lead.get("emails"),
        "phones": lead.get("phones"),
        "source": lead.get("source"),
    }


def trial(label, body, field):
    before = snapshot(read())
    resp = put(body)
    after = snapshot(read())
    changed = json.dumps(before.get(field)) != json.dumps(after.get(field))
    verdict = "WROTE" if changed else ("accepted-but-ignored" if resp.status_code < 300 else "rejected")
    print(f"  {label:38s} {resp.status_code}  {verdict}")
    if resp.status_code >= 300:
        print(f"      {resp.text[:180]}")
    if changed:
        print(f"      {json.dumps(before.get(field))[:110]}")
        print(f"   -> {json.dumps(after.get(field))[:110]}")
    return {"label": label, "status": resp.status_code, "changed": changed,
            "before": before.get(field), "after": after.get(field),
            "response": resp.text[:400]}


def main():
    start = read()
    print("=== record as found ===")
    print(json.dumps(snapshot(start), indent=2)[:900])

    print("\n=== restoring the name the verb probe changed ===")
    print("  put lastName=Guide ->", put({"lastName": "Guide"}).status_code,
          "| now:", read().get("lastName"))

    results = []
    print("\n=== field-by-field PUT trials ===")
    original_tags = read().get("tags") or []
    results.append(trial("tags: object form", {"tags": [{"tagName": "reai-probe"}]}, "tags"))
    results.append(trial("tags: string form", {"tags": ["reai-probe"]}, "tags"))
    results.append(trial("tags: empty list (strip all)", {"tags": []}, "tags"))
    results.append(trial("stage: Archived", {"stage": "Archived"}, "stage"))
    results.append(trial("emails: string form",
                         {"emails": ["reai-probe@example.com"]}, "emails"))
    results.append(trial("emails: object form",
                         {"emails": [{"email": "reai-probe@example.com"}]}, "emails"))
    results.append(trial("phones: string form", {"phones": ["9051234567"]}, "phones"))
    results.append(trial("source", {"source": "reai-probe"}, "source"))

    print("\n=== restoring original values ===")
    restore = {"firstName": start.get("firstName"), "lastName": start.get("lastName") or "Guide",
               "stage": start.get("stage"), "tags": original_tags,
               "emails": start.get("emails"), "phones": start.get("phones"),
               "source": start.get("source")}
    restore = {k: v for k, v in restore.items() if v is not None}
    resp = put(restore)
    final = snapshot(read())
    print(f"  restore -> {resp.status_code}")
    for key in ("firstName", "lastName", "stage", "tags", "emails", "phones", "source"):
        same = json.dumps(final.get(key)) == json.dumps(snapshot(start).get(key))
        print(f"    {key:10s} {'back to original' if same else 'STILL DIFFERENT: ' + json.dumps(final.get(key))[:100]}")

    OUT.write_text(json.dumps({"start": snapshot(start), "trials": results,
                               "final": final}, indent=2))
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()

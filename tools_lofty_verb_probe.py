"""Which HTTP verbs and sub-resources does the Lofty API actually expose?

PATCH turned out to be unsupported, so this maps what IS allowed. Still only
touches the Chime Guide demo record. Read requests everywhere except a couple of
deliberate writes against that one demo contact.
"""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

LEAD_ID = "1127720690818985"  # Chime Guide demo record
OUT = Path(__file__).resolve().parent / "data" / "lofty_verb_probe.json"


def call(method, path, **kw):
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.request(method, url, headers=_headers(), timeout=20, **kw)
    except requests.RequestException as exc:
        print(f"  {method:7s} {path:42s} -> ERROR {exc}")
        return None
    body = resp.text[:220].replace("\n", " ")
    print(f"  {method:7s} {path:42s} -> {resp.status_code} {body}")
    return {"status": resp.status_code, "body": resp.text[:600]}


def main():
    log = {}

    print("=== what GET /leads/{id} really returns ===")
    resp = requests.get(f"{BASE_URL}/leads/{LEAD_ID}", headers=_headers(), timeout=20)
    print(f"  status {resp.status_code}")
    try:
        payload = resp.json()
        print("  top-level keys:", list(payload.keys()))
        print(json.dumps(payload, indent=2)[:1800])
        log["get_lead"] = payload
    except ValueError:
        print("  non-json:", resp.text[:400])

    print("\n=== verbs on the single lead (demo record only) ===")
    log["options"] = call("OPTIONS", f"/leads/{LEAD_ID}")
    log["put"] = call("PUT", f"/leads/{LEAD_ID}", json={"lastName": "GuideProbe"})
    log["post_id"] = call("POST", f"/leads/{LEAD_ID}", json={"lastName": "GuideProbe"})
    log["delete"] = call("OPTIONS", "/leads")

    print("\n=== sub-resources / other endpoints (read attempts) ===")
    for path in (f"/leads/{LEAD_ID}/tags", f"/leads/{LEAD_ID}/notes",
                 f"/leads/{LEAD_ID}/activities", f"/leads/{LEAD_ID}/emails",
                 "/tags", "/leadTags", "/stages", "/pipelines", "/users",
                 "/sources", "/leadSources", "/smartLists", "/campaigns",
                 "/emailCampaigns", "/lead/search", "/leads/query"):
        log[f"GET {path}"] = call("GET", path)

    OUT.write_text(json.dumps(log, indent=2))
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()

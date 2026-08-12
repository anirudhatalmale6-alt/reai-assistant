"""Can a tag list be emptied at all, or only replaced?

Matters because 2,269 contacts carry import junk like "import20230425" and for
many of them that junk is ALL they have. If it can't be emptied we can only
swap it for one meaningful tag instead. Demo record only; also clears the
leftover probe tag.
"""
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

LEAD_ID = "1127720690818985"


def tags_now():
    resp = requests.get(f"{BASE_URL}/leads/{LEAD_ID}", headers=_headers(), timeout=20)
    resp.raise_for_status()
    return [t.get("tagName") for t in (resp.json().get("lead", {}).get("tags") or [])]


def attempt(label, body):
    resp = requests.put(f"{BASE_URL}/leads/{LEAD_ID}", headers=_headers(), json=body, timeout=20)
    time.sleep(6)
    after = tags_now()
    print(f"  {label:32s} {resp.status_code} -> tags now {after}")
    if resp.status_code >= 300:
        print(f"      {resp.text[:160]}")
    return after


def main():
    print("start:", tags_now())
    for label, body in (
        ("tags: []", {"tags": []}),
        ('tags: [""]', {"tags": [""]}),
        ("tags: null", {"tags": None}),
        ("deleteTags flag", {"tags": [], "deleteTags": True}),
    ):
        if not attempt(label, body):
            print("  -> tags CAN be emptied with this form.")
            return
    print("\n  -> tags cannot be emptied via the API; a list can only be replaced.")
    print("     Swapping the junk for one clean tag is the best the API allows.")
    attempt("replace with 'Chime demo record'", {"tags": ["Chime demo record"]})


if __name__ == "__main__":
    main()

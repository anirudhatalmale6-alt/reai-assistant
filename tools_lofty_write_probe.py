"""Find out what the Lofty API will actually let us change.

Runs against ONE record only - the "Chime Guide" demo contact the system created
itself (leadId 1127720690818985) - and puts everything back the way it found it.
Nothing real is touched. The point is to learn which cleanup steps can be
automated and which have to be done by hand in Lofty.
"""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

LEAD_ID = "1127720690818985"  # Chime Guide demo record


def fetch():
    resp = requests.get(f"{BASE_URL}/leads/{LEAD_ID}", headers=_headers(), timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("data", payload)


def patch(body, label):
    resp = requests.patch(f"{BASE_URL}/leads/{LEAD_ID}", headers=_headers(),
                          json=body, timeout=20)
    ok = resp.status_code < 300
    print(f"  {label:34s} -> {resp.status_code} {'OK' if ok else resp.text[:200]}")
    return ok


def main():
    before = fetch()
    print("=== current state of the demo record ===")
    for key in ("firstName", "lastName", "stage", "tags", "emails", "phones",
                "source", "assignedUser", "note"):
        print(f"  {key}: {json.dumps(before.get(key))[:160]}")

    print("\n=== write probes ===")
    results = {}

    # a) plain text field - the safest possible change
    results["lastName"] = patch({"lastName": "GuideProbe"}, "set lastName")

    # b) tags: can we replace the tag list? (needed to strip 2,269 import tags)
    old_tags = before.get("tags") or []
    tag_names = [t.get("tagName") or t.get("name") for t in old_tags if isinstance(t, dict)]
    results["tags_objects"] = patch({"tags": old_tags + [{"tagName": "reai-probe"}]},
                                    "add tag (object form)")
    results["tags_strings"] = patch({"tags": tag_names + ["reai-probe"]},
                                    "add tag (string form)")

    # c) stage: needed to consolidate leftover stages
    results["stage"] = patch({"stage": before.get("stage")}, "re-set same stage")

    # d) emails: needed to fix the 8 misspelled addresses
    results["emails_strings"] = patch({"emails": ["reai-probe@example.com"]},
                                      "replace emails (string form)")
    results["emails_objects"] = patch({"emails": [{"email": "reai-probe@example.com"}]},
                                      "replace emails (object form)")

    # e) phones: needed to clear the placeholder 1234567890 numbers
    results["phones"] = patch({"phones": ["9051234567"]}, "replace phones")

    # f) note
    results["note"] = patch({"note": "reai probe"}, "set note")

    after = fetch()
    print("\n=== what actually changed ===")
    for key in ("lastName", "stage", "tags", "emails", "phones", "note"):
        b, a = json.dumps(before.get(key)), json.dumps(after.get(key))
        print(f"  {key}: {'CHANGED' if a != b else 'unchanged'}")
        if a != b:
            print(f"      before: {b[:140]}")
            print(f"      after:  {a[:140]}")

    print("\n=== restoring original values ===")
    restore = {k: before.get(k) for k in
               ("firstName", "lastName", "stage", "tags", "emails", "phones") if k in before}
    patch(restore, "restore everything")
    final = fetch()
    clean = all(json.dumps(final.get(k)) == json.dumps(before.get(k))
                for k in ("lastName", "stage", "emails", "phones"))
    print(f"  restored cleanly: {clean}")
    if not clean:
        for key in ("lastName", "stage", "tags", "emails", "phones"):
            print(f"    {key}: {json.dumps(final.get(key))[:140]}")

    Path(__file__).parent.joinpath("data", "lofty_write_probe.json").write_text(
        json.dumps({"results": results, "before": before, "after": after,
                    "final": final}, indent=2))


if __name__ == "__main__":
    main()

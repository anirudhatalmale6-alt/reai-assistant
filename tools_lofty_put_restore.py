"""Put the Chime Guide demo record back exactly as it was, and settle two
questions the first PUT probe left open:

  1. Reads lag behind writes, so several "accepted-but-ignored" results were
     really successful writes. Re-check with a pause.
  2. tags:[] did not clear the tag list. Is tag writing additive (bad news for
     stripping 2,269 import tags) or does a non-empty list replace?
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

LEAD_ID = "1127720690818985"
ORIGINAL = {
    "firstName": "Chime",
    "lastName": "Guide",
    "stage": "Nurture (90+ days)",
    "emails": ["no-reply151192546984521887219@chime.me",
               "no-reply151192546984539692149@chime.me"],
    "phones": ["1234567890"],
    "source": "Other",
}


def read():
    resp = requests.get(f"{BASE_URL}/leads/{LEAD_ID}", headers=_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json().get("lead", {})


def put(body):
    return requests.put(f"{BASE_URL}/leads/{LEAD_ID}", headers=_headers(),
                        json=body, timeout=20)


def show(label):
    lead = read()
    tags = [t.get("tagName") or t.get("tagId") for t in (lead.get("tags") or [])]
    print(f"  {label}: name={lead.get('firstName')} {lead.get('lastName')} | "
          f"stage={lead.get('stage')} | source={lead.get('source')} | "
          f"emails={lead.get('emails')} | phones={lead.get('phones')} | tags={tags}")
    return lead


def main():
    show("as found")

    print("\n=== does a non-empty tag list REPLACE or ADD? ===")
    put({"tags": ["reai-probe-2"]})
    time.sleep(6)
    lead = show("after writing one different tag")
    names = {t.get("tagName") for t in (lead.get("tags") or [])}
    if names == {"reai-probe-2"}:
        print("  -> REPLACE semantics: a tag list overwrites. Junk tags CAN be stripped.")
    elif "reai-probe" in names and "reai-probe-2" in names:
        print("  -> ADDITIVE: tags accumulate. Junk tags CANNOT be removed via the API.")
    else:
        print(f"  -> unclear: {names}")

    print("\n=== restoring original field values ===")
    print("  put ->", put(ORIGINAL).status_code)
    time.sleep(8)
    lead = show("after restore")

    ok = all(str(lead.get(k)) == str(v) for k, v in ORIGINAL.items()
             if k not in ("emails", "phones"))
    emails_ok = set(lead.get("emails") or []) == set(ORIGINAL["emails"])
    phones_ok = list(lead.get("phones") or []) == ORIGINAL["phones"]
    print(f"\n  scalar fields restored: {ok}")
    print(f"  emails restored: {emails_ok}")
    print(f"  phones restored: {phones_ok}")
    leftover = [t.get("tagName") for t in (lead.get("tags") or [])]
    print(f"  leftover probe tags on the demo record: {leftover}")

    Path(__file__).resolve().parent.joinpath("data", "lofty_put_restore.json").write_text(
        json.dumps({"final": {k: lead.get(k) for k in
                              ("firstName", "lastName", "stage", "source", "emails",
                               "phones", "tags")}}, indent=2))


if __name__ == "__main__":
    main()

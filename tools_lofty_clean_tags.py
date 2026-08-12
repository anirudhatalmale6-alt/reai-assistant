"""Strip import junk out of the tag list without losing real tags.

The old imports jammed several tags into one field and Lofty truncated the
result at 30 characters, so a single "tag" often reads:

    "import20210427-28c36 #PastClie"

Deleting that whole tag would throw away a Past Client marker. So this works at
the word level: it removes only the import stamps, repairs the two truncations
we can identify with certainty, and leaves everything else exactly as it is.

Deliberately NOT touched:
  MassEmail    - might mean "ok to mass email", which would be useful, not junk
  doorknocking, MLS, Sphere, spring202..., bare numbers - his data, his meaning

Writes with --apply. Every before/after goes to data/lofty_tag_cleanup.json so
any of it can be reversed. Note this API answers 200 even when it refuses a
write, with the real result in the body, so responses are parsed properly.
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

LOG = Path(__file__).resolve().parent / "data" / "lofty_tag_cleanup.json"
INDEX = Path(__file__).resolve().parent / "data" / "crm_index.json"

# Words that carry no information: the import stamps themselves, the "iphone"
# that prefixes them, and the fragments left where a second stamp was cut off.
JUNK_WORD = re.compile(r"^(import\d{4,8}-?\w*|import\d*|impor|iphone)$", re.I)
# Truncations we can restore with confidence.
REPAIRS = {"#PastClie": "#PastClient", "MassE": "MassEmail"}


def clean_tag(tag: str) -> str:
    words = [REPAIRS.get(w, w) for w in tag.split() if not JUNK_WORD.match(w)]
    return " ".join(words).strip()


def clean_list(tags: list[str]) -> list[str]:
    out = []
    for tag in tags:
        cleaned = clean_tag(tag)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def put_tags(lead_id: str, tags: list[str]):
    resp = requests.put(f"{BASE_URL}/leads/{lead_id}", headers=_headers(),
                        json={"tags": tags}, timeout=25)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    status = (body.get("status") or {})
    if resp.status_code >= 300:
        return False, f"HTTP {resp.status_code}: {resp.text[:160]}"
    if status.get("code") and status.get("code") != 200:
        return False, f"{status.get('code')}: {status.get('msg')}"
    return True, "ok"


def main():
    apply = "--apply" in sys.argv
    contacts = json.loads(INDEX.read_text())["contacts"]

    work, empties = [], []
    for contact in contacts:
        tags = contact["tags"]
        if not any(re.search(r"import\d{4,8}|^iphone$", t, re.I) for t in tags):
            continue
        cleaned = clean_list(tags)
        if cleaned == tags:
            continue
        if not cleaned:
            empties.append(contact)   # API will not accept an empty tag list
            continue
        work.append((contact, tags, cleaned))

    print(f"{len(work)} contacts to clean, {len(empties)} skipped "
          f"(nothing would be left and the API cannot store an empty tag list)")
    print("\nsample of the change:")
    for contact, before, after in work[:8]:
        print(f"  {contact['first']} {contact['last']}".rstrip())
        print(f"      before {before}")
        print(f"      after  {after}")
    if empties:
        print("\nskipped (need doing by hand in Lofty):")
        for contact in empties:
            print(f"  {contact['first']} {contact['last']} {contact['tags']} "
                  f"https://crm.lofty.com/leads/{contact['id']}")

    if not apply:
        print(f"\nDRY RUN. Re-run with --apply to write these {len(work)} records.")
        return

    # --limit N to try a handful first and confirm they really landed
    for arg in sys.argv:
        if arg.startswith("--limit="):
            work = work[:int(arg.split("=", 1)[1])]

    print(f"\napplying to {len(work)} records...")
    log, failed = [], 0
    for i, (contact, before, after) in enumerate(work, 1):
        ok, message = put_tags(str(contact["id"]), after)
        log.append({"leadId": contact["id"],
                    "name": f"{contact['first']} {contact['last']}".strip(),
                    "before": before, "after": after, "ok": ok, "message": message})
        if not ok:
            failed += 1
            print(f"  FAILED {contact['id']} {contact['first']}: {message}", flush=True)
        if i % 100 == 0:
            print(f"  {i}/{len(work)} ({failed} failed)", flush=True)
            LOG.write_text(json.dumps(log, indent=2))
        time.sleep(0.2)

    LOG.write_text(json.dumps({"skipped_empty": [c["id"] for c in empties],
                               "records": log}, indent=2))
    print(f"\ndone: {len(work) - failed} cleaned, {failed} failed. Log: {LOG}")


if __name__ == "__main__":
    main()

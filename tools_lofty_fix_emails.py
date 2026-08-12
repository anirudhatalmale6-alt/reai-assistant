"""Correct the misspelled email addresses found by the cleanup scan.

Eight records, each a clear single-character slip (iclould.com, gmai.com,
gmail.con, ouctlook.com, hotmai.com, yaho.com, and one with a trailing full
stop). Each contact's full address list is read first and written back with only
the bad entry replaced, so nothing else on the record moves.

Writes to the live CRM. Run with --apply; without it, it only shows the plan.
Every before/after is logged to data/lofty_email_fixes.json so any of this can
be reversed.
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

LOG = Path(__file__).resolve().parent / "data" / "lofty_email_fixes.json"

# leadId -> (wrong address, corrected address). Taken from cleanup-1-fixable-emails.csv.
FIXES = {
    "1128965405311312": ("oppyeah@iclould.com", "oppyeah@icloud.com"),
    "1132782410559402": ("brandonvelelago@gmai.com", "brandonvelelago@gmail.com"),
    "1146750851184295": ("david.delgrosso@hotmai.com", "david.delgrosso@hotmail.com"),
    "1148388034970420": ("gurshansidhu0808@gmail.con", "gurshansidhu0808@gmail.com"),
    "1146375778934952": ("darisgaray@ouctlook.com", "darisgaray@outlook.com"),
    "1127616735558743": ("skipy26@hotmail.com.", "skipy26@hotmail.com"),
    "1127734652275371": ("m@yaho.com", "m@yahoo.com"),
    "835615072576582": ("yup@gmail.con", "yup@gmail.com"),
}


def read(lead_id):
    resp = requests.get(f"{BASE_URL}/leads/{lead_id}", headers=_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json().get("lead", {})


def main():
    apply = "--apply" in sys.argv
    print("APPLYING CHANGES" if apply else "DRY RUN - nothing will be written")
    log = []

    for lead_id, (wrong, right) in FIXES.items():
        lead = read(lead_id)
        name = f"{lead.get('firstName') or ''} {lead.get('lastName') or ''}".strip()
        current = list(lead.get("emails") or [])
        if wrong not in current:
            print(f"  {name:22s} SKIP - '{wrong}' is no longer on the record ({current})")
            log.append({"leadId": lead_id, "name": name, "action": "skipped",
                        "reason": "address not found", "emails": current})
            continue
        if right in current:
            print(f"  {name:22s} SKIP - '{right}' is already there too")
            log.append({"leadId": lead_id, "name": name, "action": "skipped",
                        "reason": "correct address already present", "emails": current})
            continue

        updated = [right if e == wrong else e for e in current]
        print(f"  {name:22s} {wrong}  ->  {right}")
        entry = {"leadId": lead_id, "name": name, "before": current, "intended": updated}

        if apply:
            resp = requests.put(f"{BASE_URL}/leads/{lead_id}", headers=_headers(),
                                json={"emails": updated}, timeout=20)
            entry["status"] = resp.status_code
            if resp.status_code >= 300:
                entry["error"] = resp.text[:300]
                print(f"      FAILED {resp.status_code}: {resp.text[:160]}")
            else:
                time.sleep(5)  # reads lag behind writes on this API
                entry["after"] = list(read(lead_id).get("emails") or [])
                ok = right in entry["after"] and wrong not in entry["after"]
                entry["verified"] = ok
                print(f"      {'verified' if ok else 'WROTE BUT NOT CONFIRMED: ' + str(entry['after'])}")
        log.append(entry)

    if apply:
        LOG.write_text(json.dumps(log, indent=2))
        done = sum(1 for e in log if e.get("verified"))
        print(f"\n{done}/{len(FIXES)} corrected and verified. Rollback data in {LOG}")
    else:
        print(f"\n{len(FIXES)} records would be updated. Re-run with --apply.")


if __name__ == "__main__":
    main()

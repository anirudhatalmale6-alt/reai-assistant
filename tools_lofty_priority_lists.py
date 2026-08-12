"""The two lists worth acting on this week.

The cleanup scan turned up something more useful than tidy tags: people who told
Lofty's AI they wanted a call or a showing are parked in Nurture, Archived and
Dead Leads. And most of the contacts marked as past clients are sitting in
Archived, which for a realtor is the last place they belong.

Read-only. Produces two CSVs with phone numbers, so these can be worked straight
down the list.
"""
import csv
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "data" / "exports"
INDEX = Path(__file__).resolve().parent / "data" / "crm_index.json"

# Stages that mean "nobody is working this person".
COLD_STAGES = {"Nurture (90+ days)", "Archived", "Dead Leads",
               "Renters with Email", "Renters with Form", "Renters No Email"}
# Tags that mean the opposite.
SIGNALS = {
    "AI: Asked for a Call": "asked for a call",
    "AI: Requested Showing": "requested a showing",
    "AI: Interested": "said they were interested",
    "AI: Warm": "warm per Lofty's AI",
}
PAST_CLIENT = ("#PastClie", "PastClient", "Past Client")


def details(lead_id):
    """Phone numbers aren't in the local index, so pull the real record."""
    try:
        resp = requests.get(f"{BASE_URL}/leads/{lead_id}", headers=_headers(), timeout=20)
        resp.raise_for_status()
        lead = resp.json().get("lead") or {}
        return (", ".join(str(p) for p in (lead.get("phones") or []) if p),
                ", ".join(lead.get("emails") or []),
                lead.get("lastUpdateTime") or "", lead.get("createTime") or "")
    except (requests.RequestException, ValueError):
        return "", "", "", ""


def write(name, header, rows):
    path = OUT_DIR / name
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    contacts = json.loads(INDEX.read_text())["contacts"]

    def tagged(contact, *needles):
        return [t for t in contact["tags"]
                if any(n.lower() in t.lower() for n in needles)]

    # 1. Live buying signals parked in cold stages, hottest signal first.
    order = list(SIGNALS)
    rows = []
    for contact in contacts:
        if contact["stage"] not in COLD_STAGES:
            continue
        if any(t.strip().lower() == "ai: dnc" for t in contact["tags"]):
            continue  # asked not to be contacted
        hits = [SIGNALS[k] for k in order if tagged(contact, k)]
        if not hits:
            continue
        rank = min(order.index(k) for k in order if tagged(contact, k))
        rows.append((rank, contact, "; ".join(hits)))
    rows.sort(key=lambda r: r[0])

    print(f"fetching phone numbers for {len(rows)} contacts...", flush=True)
    out = []
    for i, (_, contact, signal) in enumerate(rows, 1):
        phone, emails, updated, created = details(contact["id"])
        out.append([signal, f"{contact['first']} {contact['last']}".strip(), phone, emails,
                    contact["stage"], contact["source"], contact["owner"], created, updated,
                    f"https://crm.lofty.com/leads/{contact['id']}"])
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}", flush=True)
    write("action-1-buying-signals-in-cold-stages.csv",
          ["Signal", "Name", "Phone", "Email", "Currently In", "Source", "Owner",
           "Created", "Last Updated", "Open in Lofty"], out)

    # 2. Past clients that got archived.
    rows = [c for c in contacts
            if tagged(c, *PAST_CLIENT) and c["stage"] != "Past Clients"]
    out = []
    for contact in rows:
        phone, emails, updated, created = details(contact["id"])
        out.append([f"{contact['first']} {contact['last']}".strip(), phone, emails,
                    contact["stage"], "; ".join(contact["tags"]), contact["owner"],
                    created, f"https://crm.lofty.com/leads/{contact['id']}"])
    write("action-2-past-clients-archived.csv",
          ["Name", "Phone", "Email", "Currently In", "Tags", "Owner", "Created",
           "Open in Lofty"], out)

    print(f"\nwritten to {OUT_DIR}")


if __name__ == "__main__":
    main()

"""Read-only cleanup worklists for the Lofty database.

Produces one CSV per problem so each can be worked through (or handed to an
assistant) without anybody having to trawl 8,384 records. Changes nothing in
the CRM.
"""
import collections
import csv
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402
from app.services.segments import (BLOCKED_DOMAINS, EMAIL_RE,  # noqa: E402
                                   TYPO_DOMAINS, email_problem)

OUT_DIR = Path(__file__).resolve().parent / "data" / "exports"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Best guess at what each misspelling was meant to be.
CORRECTIONS = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmail.co": "gmail.com",
    "gmail.con": "gmail.com", "gmail.cm": "gmail.com", "gnail.com": "gmail.com",
    "gmaill.com": "gmail.com", "hotmial.com": "hotmail.com", "hotmail.co": "hotmail.com",
    "hotmail.con": "hotmail.com", "hotmai.com": "hotmail.com", "hotmial.co": "hotmail.com",
    "yaho.com": "yahoo.com", "yahoo.co": "yahoo.com", "yahooo.com": "yahoo.com",
    "yahoo.con": "yahoo.com", "ymail.co": "ymail.com", "ouctlook.com": "outlook.com",
    "outlok.com": "outlook.com", "outlook.co": "outlook.com", "outloo.com": "outlook.com",
    "otlook.com": "outlook.com", "icloud.co": "icloud.com", "iclould.com": "icloud.com",
}
JUNK_TAG_RE = re.compile(r"(import\d{8}|^import|iphone import|masse?mail)", re.I)
TEST_PHONES = {"1234567890", "9055555555", "0000000000", "1111111111"}
TEST_NAMES = {"chime guide", "lofty guide", "me", "test test", "test"}


def emails_of(lead):
    out = []
    for entry in lead.get("emails") or []:
        if isinstance(entry, str):
            out.append(entry.strip())
        elif isinstance(entry, dict):
            value = (entry.get("email") or entry.get("value") or "").strip()
            if value:
                out.append(value)
    return out


def digits(value):
    return re.sub(r"\D", "", str(value or ""))[-10:]


def write_csv(name, header, rows):
    path = OUT_DIR / name
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  {name}: {len(rows)} rows")
    return path


def scan():
    headers = _headers()
    leads, scroll, total = [], None, 0
    while True:
        params = {"limit": 100}
        if scroll:
            params["scrollId"] = scroll
        resp = requests.get(f"{BASE_URL}/leads", headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("leads") or []
        meta = payload.get("_metadata") or {}
        total, scroll = meta.get("total", total), meta.get("scrollId")
        if not batch:
            break
        leads.extend(batch)
        if len(leads) % 1000 == 0:
            print(f"scanned {len(leads)}/{total}", flush=True)
        if len(leads) >= total or not scroll:
            break
        time.sleep(0.15)
    print(f"scanned {len(leads)}/{total}", flush=True)
    return leads


def main():
    leads = scan()
    print("\nwriting worklists:")

    def name_of(lead):
        return f"{(lead.get('firstName') or '').strip()} {(lead.get('lastName') or '').strip()}".strip()

    def lofty_link(lead):
        return f"https://crm.lofty.com/leads/{lead.get('leadId')}"

    # 1. Fixable email addresses - typos and malformed, with a suggested correction
    rows = []
    for lead in leads:
        for address in emails_of(lead):
            low = address.lower()
            domain = low.rsplit("@", 1)[-1] if "@" in low else ""
            problem = email_problem(address)
            if not problem or domain in BLOCKED_DOMAINS:
                continue  # vendor placeholders are handled separately, they aren't fixable
            suggestion = ""
            if domain in CORRECTIONS:
                suggestion = low.rsplit("@", 1)[0] + "@" + CORRECTIONS[domain]
            elif not EMAIL_RE.match(low):
                cleaned = re.sub(r"[\s ]", "", low).rstrip(".")
                if EMAIL_RE.match(cleaned):
                    suggestion = cleaned
            rows.append([name_of(lead), address, problem, suggestion,
                         lead.get("stage") or "", lead.get("assignedUser") or "", lofty_link(lead)])
    write_csv("cleanup-1-fixable-emails.csv",
              ["Name", "Current Email", "Problem", "Suggested Fix", "Stage", "Owner", "Open in Lofty"],
              sorted(rows))

    # 2. Vendor placeholder addresses - not fixable, needs a real email or phone-only outreach
    rows = [[name_of(l), e, l.get("stage") or "", (l.get("phones") or [""])[0],
             l.get("assignedUser") or "", lofty_link(l)]
            for l in leads for e in emails_of(l)
            if e.lower().rsplit("@", 1)[-1] in BLOCKED_DOMAINS]
    write_csv("cleanup-2-fake-vendor-emails.csv",
              ["Name", "Fake Email", "Stage", "Phone", "Owner", "Open in Lofty"], sorted(rows))

    # 3. Duplicates by phone, then by name
    by_phone = collections.defaultdict(list)
    by_name = collections.defaultdict(list)
    for lead in leads:
        for phone in lead.get("phones") or []:
            key = digits(phone)
            if len(key) == 10 and key not in TEST_PHONES:
                by_phone[key].append(lead)
        if name_of(lead):
            by_name[name_of(lead).lower()].append(lead)

    rows = []
    for key, group in sorted(by_phone.items()):
        if len(group) < 2:
            continue
        for lead in group:
            rows.append(["phone", key, name_of(lead), (emails_of(lead) or [""])[0],
                         lead.get("stage") or "", lead.get("createTime") or "",
                         lead.get("assignedUser") or "", lofty_link(lead)])
    seen_phone_ids = {r[7] for r in rows}
    for key, group in sorted(by_name.items()):
        if len(group) < 2 or key in TEST_NAMES:
            continue
        for lead in group:
            if lofty_link(lead) in seen_phone_ids:
                continue  # already listed under the phone match
            rows.append(["name", key, name_of(lead), (emails_of(lead) or [""])[0],
                         lead.get("stage") or "", lead.get("createTime") or "",
                         lead.get("assignedUser") or "", lofty_link(lead)])
    write_csv("cleanup-3-duplicates.csv",
              ["Matched On", "Match Key", "Name", "Email", "Stage", "Created", "Owner", "Open in Lofty"],
              rows)

    # 4. Unreachable - no email and no phone
    rows = [[name_of(l), l.get("stage") or "", l.get("source") or "",
             l.get("createTime") or "", l.get("assignedUser") or "", lofty_link(l)]
            for l in leads if not emails_of(l) and not [p for p in (l.get("phones") or []) if p]]
    write_csv("cleanup-4-unreachable.csv",
              ["Name", "Stage", "Source", "Created", "Owner", "Open in Lofty"], sorted(rows))

    # 5. Contacts carrying import-junk tags
    rows = []
    for lead in leads:
        junk = [t.get("tagName") or t.get("name") or "" for t in (lead.get("tags") or [])
                if JUNK_TAG_RE.search(t.get("tagName") or t.get("name") or "")]
        if junk:
            rows.append([name_of(lead), "; ".join(junk), lead.get("stage") or "",
                         l_owner if (l_owner := lead.get("assignedUser")) else "", lofty_link(lead)])
    write_csv("cleanup-5-junk-tags.csv",
              ["Name", "Junk Tags", "Stage", "Owner", "Open in Lofty"], sorted(rows))

    # 6. Unassigned
    rows = [[name_of(l), (emails_of(l) or [""])[0], l.get("stage") or "",
             l.get("source") or "", lofty_link(l)]
            for l in leads if not (l.get("assignedUser") or "").strip()]
    write_csv("cleanup-6-unassigned.csv",
              ["Name", "Email", "Stage", "Source", "Open in Lofty"], sorted(rows))

    # 7. Obvious test / demo records still in the live database
    rows = [[name_of(l), (emails_of(l) or [""])[0], (l.get("phones") or [""])[0],
             l.get("stage") or "", lofty_link(l)]
            for l in leads
            if name_of(l).lower() in TEST_NAMES
            or any(digits(p) in TEST_PHONES for p in (l.get("phones") or []))]
    write_csv("cleanup-7-test-records.csv",
              ["Name", "Email", "Phone", "Stage", "Open in Lofty"], sorted(rows))

    print(f"\nall worklists in {OUT_DIR}")


if __name__ == "__main__":
    main()

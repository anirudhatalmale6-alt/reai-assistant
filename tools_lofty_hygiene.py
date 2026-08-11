"""Read-only CRM hygiene audit: what's broken or messy in the Lofty database.

Finds the things that quietly cost money - typo'd email domains that bounce,
duplicate people, contacts with no way to reach them, import-junk tags, and
stages that no longer mean anything. Changes nothing.
"""
import collections
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.services.lofty import BASE_URL, _headers  # noqa: E402

OUT = Path(__file__).resolve().parent / "data" / "lofty_hygiene.json"

# Domains that are almost certainly a typo of a real provider.
TYPO_DOMAINS = {
    "gmial.com", "gmai.com", "gmail.co", "gmail.con", "gmail.cm", "gnail.com", "gmaill.com",
    "hotmial.com", "hotmail.co", "hotmail.con", "hotmai.com", "hotmial.co",
    "yaho.com", "yahoo.co", "yahooo.com", "yahoo.con", "ymail.co",
    "ouctlook.com", "outlok.com", "outlook.co", "outloo.com", "otlook.com",
    "icloud.co", "iclould.com", "sympatico.c", "rogers.co", "bell.ne",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
JUNK_TAG_RE = re.compile(r"(import\d{8}|^import|iphone import|masse?mail)", re.I)


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
        total = meta.get("total", total)
        scroll = meta.get("scrollId")
        if not batch:
            break
        leads.extend(batch)
        print(f"scanned {len(leads)}/{total}", flush=True)
        if len(leads) >= total or not scroll:
            break
        time.sleep(0.15)
    return leads


def main():
    leads = scan()
    report = {"scanned": len(leads)}

    bad_format, typo, no_contact, no_name, unassigned = [], [], 0, 0, 0
    by_email = collections.defaultdict(list)
    by_phone = collections.defaultdict(list)
    by_name = collections.defaultdict(list)
    junk_tags = collections.Counter()
    tag_usage = collections.Counter()
    stage_age = collections.defaultdict(list)
    no_stage = 0

    for lead in leads:
        name = f"{(lead.get('firstName') or '').strip()} {(lead.get('lastName') or '').strip()}".strip()
        addresses = emails_of(lead)
        phones = [p for p in (lead.get("phones") or []) if p]

        if not name:
            no_name += 1
        if not addresses and not phones:
            no_contact += 1
        if not (lead.get("assignedUser") or "").strip():
            unassigned += 1
        if not (lead.get("stage") or "").strip():
            no_stage += 1

        for address in addresses:
            low = address.lower()
            if not EMAIL_RE.match(low):
                bad_format.append({"lead": name, "email": address})
            domain = low.rsplit("@", 1)[-1] if "@" in low else ""
            if domain in TYPO_DOMAINS:
                typo.append({"lead": name, "email": address, "leadId": lead.get("leadId")})
            by_email[low].append(name)

        for phone in phones:
            digits = re.sub(r"\D", "", str(phone))[-10:]
            if len(digits) == 10:
                by_phone[digits].append(name)

        if name:
            by_name[name.lower()].append(lead.get("leadId"))

        for tag in lead.get("tags") or []:
            tag_name = tag.get("tagName") or tag.get("name") or ""
            if tag_name:
                tag_usage[tag_name] += 1
                if JUNK_TAG_RE.search(tag_name):
                    junk_tags[tag_name] += 1

        created = (lead.get("createTime") or "")[:4]
        if created.isdigit():
            stage_age[lead.get("stage") or "(no stage)"].append(int(created))

    dup_emails = {e: n for e, n in by_email.items() if len(n) > 1}
    dup_phones = {p: n for p, n in by_phone.items() if len(n) > 1}
    dup_names = {n: ids for n, ids in by_name.items() if len(ids) > 1}

    report.update({
        "unreachable_no_email_no_phone": no_contact,
        "missing_name": no_name,
        "unassigned": unassigned,
        "missing_stage": no_stage,
        "malformed_emails": {"count": len(bad_format), "examples": bad_format[:12]},
        "typo_domain_emails": {"count": len(typo), "examples": typo[:15]},
        "duplicate_email_addresses": {
            "count": len(dup_emails),
            "extra_records": sum(len(v) - 1 for v in dup_emails.values()),
            "examples": [{"email": e, "names": n} for e, n in list(dup_emails.items())[:10]],
        },
        "duplicate_phone_numbers": {
            "count": len(dup_phones),
            "extra_records": sum(len(v) - 1 for v in dup_phones.values()),
            "examples": [{"phone": p, "names": n} for p, n in list(dup_phones.items())[:10]],
        },
        "duplicate_names": {
            "count": len(dup_names),
            "examples": list(dup_names.keys())[:15],
        },
        "junk_import_tags": {
            "count": len(junk_tags),
            "contacts_tagged": sum(junk_tags.values()),
            "tags": junk_tags.most_common(15),
        },
        "tags_total": len(tag_usage),
        "single_use_tags": sum(1 for c in tag_usage.values() if c == 1),
        "stage_oldest_year": {s: min(y) for s, y in stage_age.items() if y},
        "stage_newest_year": {s: max(y) for s, y in stage_age.items() if y},
    })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))
    print("\n=== HYGIENE SUMMARY ===")
    for key in ("scanned", "unreachable_no_email_no_phone", "missing_name", "unassigned",
                "missing_stage", "tags_total", "single_use_tags"):
        print(f"{key}: {report[key]}")
    for key in ("malformed_emails", "typo_domain_emails", "duplicate_email_addresses",
                "duplicate_phone_numbers", "duplicate_names", "junk_import_tags"):
        block = report[key]
        print(f"{key}: count={block.get('count')} extra={block.get('extra_records', '')} "
              f"tagged={block.get('contacts_tagged', '')}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

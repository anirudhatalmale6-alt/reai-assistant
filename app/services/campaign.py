"""Build a branded marketing email plus the recipient list to send it to.

This module never sends anything. It produces three artefacts the agent can
review before a single email leaves: an HTML preview he can open, a plain-text
version, and the recipient list as CSV and as a paste-ready address list.

The send itself happens in Lofty's own campaign tool, because Lofty's API
exposes no campaign endpoint. That also means Lofty appends the unsubscribe
footer CASL requires.
"""
import csv
import hashlib
import html
import os
import re
import shutil
from pathlib import Path

from app.services import graphics, segments

BASE_DIR = Path(__file__).resolve().parent.parent
PREVIEW_DIR = BASE_DIR / "static" / "generated"
EXPORT_DIR = BASE_DIR.parent / "data" / "exports"
STATIC_LOGO = BASE_DIR / "static" / "brand-logo.png"

PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://reai.owlhouserealty.com").rstrip("/")


def _publish_logo(brand: dict) -> str:
    """Email clients need an absolute URL, so mirror the logo into /static."""
    logo_path = None
    for candidate in (Path(brand.get("logo") or ""), graphics.BRAND_DIR / (brand.get("logo") or "")):
        if candidate.name and candidate.is_file():
            logo_path = candidate
            break
    if logo_path is None:
        return ""
    if not STATIC_LOGO.exists() or STATIC_LOGO.stat().st_mtime < logo_path.stat().st_mtime:
        shutil.copyfile(logo_path, STATIC_LOGO)
    return f"{PUBLIC_BASE_URL}/static/brand-logo.png"


def _inline(text: str) -> str:
    """Escape for HTML, then honour the light markdown the copy often arrives in.

    Without this, **Open House Saturday** ships to 6,000 inboxes with the
    asterisks still in it.
    """
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", out)
    out = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)",
                 r'<a href="\2" style="color:inherit;">\1</a>', out)
    return out.replace("*", "")  # anything left over is a stray


def _strip_markdown(text: str) -> str:
    """Plain-text version: drop the markers rather than render them."""
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    out = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r"\1 (\2)", out)
    return out.replace("*", "")


def build_email(subject: str, headline: str, paragraphs: list[str],
                price: str = "", address: str = "", features: list[str] | None = None,
                bullets: list[str] | None = None, bullets_title: str = "",
                closing: list[str] | None = None,
                cta_text: str = "", cta_url: str = "", image_url: str = "",
                preheader: str = "") -> dict:
    """Render the email. Table-based and inline-styled, because that is what
    Outlook and Gmail actually render reliably.

    `features` are the short chips that sit in one row (3 Bed, 2 Bath). Anything
    longer than a couple of words belongs in `bullets` instead - chips are laid
    out as a single table row, so long ones push the email past 600px wide and
    Outlook will not wrap them.
    """
    brand = graphics.load_brand()
    primary, accent = brand["primary"], brand["accent"]
    logo_url = _publish_logo(brand)
    features = [f for f in (features or []) if f]
    bullets = [b for b in (bullets or []) if b]

    esc = html.escape
    para = lambda p: (  # noqa: E731
        f'<p style="margin:0 0 16px;font:16px/1.6 Arial,Helvetica,sans-serif;color:#333;">'
        f'{_inline(p)}</p>'
    )
    body_html = "".join(para(p) for p in paragraphs if p)
    # Copy that has to land after the highlights - the "reply and I'll send you
    # the details" line reads as an afterthought if it sits above the bullets.
    closing_html = "".join(para(p) for p in (closing or []) if p)

    # A real list, not chips. Built from table rows with a drawn dot rather than
    # <ul>, because Outlook's list indentation is unreliable and Gmail strips
    # list-style on some clients.
    bullets_html = ""
    if bullets:
        rows = "".join(
            f'<tr>'
            f'<td valign="top" style="width:18px;padding:0 0 9px;'
            f'font:16px/1.6 Arial,Helvetica,sans-serif;color:{accent};">&bull;</td>'
            f'<td style="padding:0 0 9px;font:16px/1.6 Arial,Helvetica,sans-serif;'
            f'color:#333;">{_inline(b)}</td>'
            f'</tr>'
            for b in bullets
        )
        title = (f'<div style="margin:0 0 10px;font:700 15px Arial,Helvetica,sans-serif;'
                 f'color:{primary};letter-spacing:.4px;text-transform:uppercase;">'
                 f'{esc(bullets_title)}</div>') if bullets_title else ""
        bullets_html = (
            f'<div style="margin:0 0 20px;">{title}'
            f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">'
            f'{rows}</table></div>'
        )

    feature_html = ""
    if features:
        cells = "".join(
            f'<td style="padding:8px 14px;font:14px Arial,Helvetica,sans-serif;'
            f'color:{primary};background:#f4f1ea;border-radius:4px;">{esc(f)}</td>'
            f'<td style="width:8px;"></td>'
            for f in features
        )
        feature_html = f'<table role="presentation" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>'

    price_html = ""
    if price or address:
        price_html = (
            f'<div style="margin:0 0 18px;">'
            f'<div style="font:700 28px Arial,Helvetica,sans-serif;color:{accent};">{esc(price)}</div>'
            f'<div style="font:15px Arial,Helvetica,sans-serif;color:#555;margin-top:4px;">{esc(address)}</div>'
            f'</div>'
        )

    image_html = ""
    if image_url:
        src = image_url if image_url.startswith("http") else f"{PUBLIC_BASE_URL}{image_url}"
        image_html = (f'<img src="{esc(src)}" alt="{esc(address or headline)}" '
                      f'style="display:block;width:100%;max-width:600px;height:auto;">')

    cta_html = ""
    if cta_text:
        href = cta_url or f"{PUBLIC_BASE_URL}"
        cta_html = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 4px;"><tr>'
            f'<td style="background:{accent};border-radius:6px;">'
            f'<a href="{esc(href)}" style="display:inline-block;padding:13px 26px;'
            f'font:700 15px Arial,Helvetica,sans-serif;color:{primary};text-decoration:none;">'
            f'{esc(cta_text)}</a></td></tr></table>'
        )

    logo_html = (f'<img src="{logo_url}" alt="{esc(brand["name"])}" '
                 f'style="display:block;height:44px;width:auto;">') if logo_url else \
                (f'<div style="font:700 18px Arial,Helvetica,sans-serif;color:{accent};">'
                 f'{esc(brand["name"])}</div>')

    contact_bits = " &nbsp;|&nbsp; ".join(
        esc(b) for b in [brand.get("agent"), brand.get("phone"), brand.get("website")] if b)

    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{esc(subject)}</title></head>
<body style="margin:0;padding:0;background:#eceff3;">
<div style="display:none;font-size:1px;color:#eceff3;">{esc(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eceff3;padding:24px 12px;">
<tr><td align="center">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:100%;background:#ffffff;border-radius:8px;overflow:hidden;">
    <tr><td style="background:{primary};padding:20px 28px;">{logo_html}</td></tr>
    <tr><td style="height:4px;background:{accent};"></td></tr>
    {f'<tr><td>{image_html}</td></tr>' if image_html else ''}
    <tr><td style="padding:28px 28px 8px;">
      <h1 style="margin:0 0 18px;font:700 25px/1.3 Georgia,'Times New Roman',serif;color:{primary};">{_inline(headline)}</h1>
      {price_html}
      {body_html}
      {bullets_html}
      {feature_html}
      {closing_html}
    </td></tr>
    <tr><td style="padding:14px 28px 28px;">{cta_html}</td></tr>
    <tr><td style="background:{primary};padding:20px 28px;font:13px Arial,Helvetica,sans-serif;color:#cfd6de;">
      {contact_bits}
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""

    text_lines = [_strip_markdown(headline), ""]
    if price:
        text_lines.append(price)
    if address:
        text_lines.append(address)
    if price or address:
        text_lines.append("")
    text_lines.extend([_strip_markdown(p) for p in paragraphs if p])
    if bullets:
        text_lines.append("")
        if bullets_title:
            text_lines.append(bullets_title)
        text_lines += [f"- {_strip_markdown(b)}" for b in bullets]
    if features:
        text_lines += ["", " | ".join(features)]
    if closing:
        text_lines += [""] + [_strip_markdown(p) for p in closing if p]
    if cta_text:
        text_lines += ["", cta_text, cta_url or PUBLIC_BASE_URL]
    footer = " | ".join(b for b in [brand.get("agent"), brand.get("phone"), brand.get("website")] if b)
    text_lines += ["", "--", footer]

    return {"subject": subject, "html": doc, "text": "\n".join(text_lines)}


def save_campaign(email: dict, recipients: list[dict], label: str = "deal-of-the-week") -> dict:
    """Write the preview + recipient exports and return their URLs."""
    stamp = hashlib.sha1(
        (email["subject"] + str(len(recipients)) + email["html"][:400]).encode()
    ).hexdigest()[:8]
    slug = graphics._slug(label)

    preview = PREVIEW_DIR / f"{slug}-{stamp}.html"
    preview.write_text(email["html"])

    csv_path = EXPORT_DIR / f"{slug}-{stamp}.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["First Name", "Last Name", "Email", "Stage", "Source", "Owner"])
        for person in recipients:
            writer.writerow([person["first"], person["last"], person["email"],
                             person["stage"], person["source"], person["owner"]])

    addresses = EXPORT_DIR / f"{slug}-{stamp}-emails.txt"
    addresses.write_text(", ".join(p["email"] for p in recipients))

    return {
        "recipients": len(recipients),
        "subject": email["subject"],
        "preview_url": f"{PUBLIC_BASE_URL}/static/generated/{preview.name}",
        "preview_file": preview.name,
        "recipient_csv_url": f"{PUBLIC_BASE_URL}/api/exports/{csv_path.name}",
        "address_list_url": f"{PUBLIC_BASE_URL}/api/exports/{addresses.name}",
        "plain_text": email["text"],
        "next_step": ("Nothing has been sent. Open the preview, and if it looks right, "
                      "create the campaign in Lofty, paste this recipient list in, and send. "
                      "Lofty adds the unsubscribe footer that Canadian law requires."),
    }


def prepare_deal_of_the_week(subject: str, headline: str, paragraphs: list[str],
                             price: str = "", address: str = "", features: list[str] | None = None,
                             bullets: list[str] | None = None, bullets_title: str = "",
                             closing: list[str] | None = None,
                             cta_text: str = "", cta_url: str = "", image_url: str = "",
                             preheader: str = "", stages: list[str] | None = None,
                             sources: list[str] | None = None, tags: list[str] | None = None,
                             owner: str | None = None, exclude_stages: list[str] | None = None,
                             cities: list[str] | None = None, limit: int | None = None) -> dict:
    """Build the email and pick the audience in one step, ready for review."""
    picked = segments.select(stages=stages, sources=sources, tags=tags, owner=owner,
                             exclude_stages=exclude_stages, cities=cities, limit=limit)
    email = build_email(subject=subject, headline=headline, paragraphs=paragraphs,
                        price=price, address=address, features=features,
                        bullets=bullets, bullets_title=bullets_title, closing=closing,
                        cta_text=cta_text, cta_url=cta_url, image_url=image_url,
                        preheader=preheader)
    saved = save_campaign(email, picked["recipients"])
    saved["sample_recipients"] = picked["sample"]
    saved["warnings"] = picked["warnings"]
    saved["excluded_note"] = ("Contacts with no email address, marked do-not-email, or already "
                              "unsubscribed were left out automatically.")
    return saved


def send_test(preview: str, to: str, subject: str = "") -> dict:
    """Email a built campaign to one address so it can be looked at properly.

    Agostino asked for "send it to me first" and got a chat summary pasted into
    a plain-text email - recipient counts, tick marks, a wall of admin. What he
    wanted was the actual email, looking the way it will look when it lands.
    This sends the rendered HTML, so the test is the thing itself.

    `preview` is either the filename or the full preview URL returned when the
    campaign was built.
    """
    name = preview.rstrip("/").rsplit("/", 1)[-1]
    if not name.endswith(".html"):
        name += ".html"
    path = PREVIEW_DIR / name
    # Filename comes from the model, so keep it inside the preview directory.
    if not path.is_file() or path.parent != PREVIEW_DIR:
        raise ValueError(f"No preview called {name}. Build the campaign first.")

    doc = path.read_text()
    if not subject:
        match = re.search(r"<title>(.*?)</title>", doc, re.S)
        subject = html.unescape(match.group(1).strip()) if match else "Campaign preview"

    # Merge fields are for the CRM to fill in. Left as-is they arrive as a
    # literal "Hi {First Name}," in his test, which reads like a broken email.
    doc = doc.replace("{First Name}", "there")

    from app.services import gmail
    result = gmail.send_email(
        to=to,
        subject=f"[Test] {subject}",
        body=("This is a test of your campaign email. It is the real thing, "
              "exactly as recipients will see it, with the merge field filled "
              "in as 'there'. Nothing has been sent to anybody else."),
        html=doc,
    )
    return {"status": result.get("status"), "sent_to": to, "subject": f"[Test] {subject}",
            "preview_file": name,
            "note": "This went to you only. No contact in the CRM received anything."}

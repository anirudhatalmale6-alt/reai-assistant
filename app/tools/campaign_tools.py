from app.services import campaign, segments

SEGMENT_FIELDS = {
    "stages": {"type": "array", "items": {"type": "string"},
               "description": "Pipeline stages to include, e.g. ['Nurture (90+ days)', 'Warm (30-90days)']. Names must match the CRM exactly - call list_crm_segments first."},
    "sources": {"type": "array", "items": {"type": "string"},
                "description": "Lead sources to include, e.g. ['Open House', 'Realtor.ca']"},
    "tags": {"type": "array", "items": {"type": "string"},
             "description": "Tags to include, e.g. ['Sphere', 'Past Client']"},
    "cities": {"type": "array", "items": {"type": "string"}, "description": "Cities to include"},
    "owner": {"type": "string",
              "description": "Only contacts assigned to this agent, e.g. 'Agostino Calandrino'. Leave empty to include the whole team - the other agents are on Agostino's team and he earns commission on their closed deals, so team-wide sends are intended. Only set this when he explicitly asks for just his own."},
    "exclude_stages": {"type": "array", "items": {"type": "string"},
                       "description": "Stages to leave out, e.g. ['Dead Leads', 'AGENTS']"},
    "limit": {"type": "integer", "description": "Cap the recipient count (useful for a first test send)"},
}

TOOLS = [
    {
        "name": "list_crm_segments",
        "description": ("Show what audience segments exist in the CRM - every pipeline stage, lead "
                        "source, tag, city and assigned agent - each with how many contacts it holds "
                        "and how many of those can actually be emailed. Always call this before "
                        "building a bulk email so segment names are exact. Contacts with no email "
                        "address, marked do-not-email, or unsubscribed are counted separately and "
                        "are never emailable."),
        "input_schema": {
            "type": "object",
            "properties": {
                "refresh": {"type": "boolean",
                            "description": "Re-scan the CRM instead of using the cached copy (slower, ~30s). Use if the agent says they just changed contacts.",
                            "default": False},
            },
        },
    },
    {
        "name": "count_crm_segment",
        "description": ("Count exactly how many people a segment would email, and show a few example "
                        "names, WITHOUT building or sending anything. Use this to confirm the audience "
                        "with the agent before drafting. Warns if the list exceeds the daily sending "
                        "limit their CRM plan allows."),
        "input_schema": {"type": "object", "properties": dict(SEGMENT_FIELDS)},
    },
    {
        "name": "prepare_deal_of_the_week",
        "description": (
            "Build a branded marketing email and pick its audience, ready for the agent to review. "
            "SENDS NOTHING - it returns a preview link plus the recipient list to paste into the CRM's "
            "campaign tool, and the agent does the final send there. Use for Deal of the Week, new "
            "listings, open house invites, price improvements and market updates. "
            "Write the copy yourself: a subject line that earns an open, a headline, and two to four "
            "short paragraphs in the agent's voice - warm, specific, no estate-agent cliches. "
            "Always confirm the segment with count_crm_segment first, and always show the agent the "
            "preview link and recipient count before they send.\n"
            "\n"
            "DEAL OF THE WEEK HOUSE STYLE - Agostino signed this off, so follow it unless he says "
            "otherwise on the day. It is a TEASER. The reply is the lead, so the email deliberately "
            "withholds enough that he gets asked:\n"
            "  - ONE property per week, never a list of several.\n"
            "  - Price IN. Street address OUT. Keep the city ('Hamilton, Ontario') as the address "
            "    field, or half the list assumes it is nowhere near them.\n"
            "  - No MLS number - an MLS number is the address, anyone looks it up in seconds.\n"
            "  - No hero image unless it is HIS OWN listing and he supplied the photo.\n"
            "  - Three to five short bullets, not seven.\n"
            "  - Say the quiet part in the closing: \"I've left the address out on purpose. Reply to "
            "    this email and I'll send you the address, the photos and the full details.\" Being "
            "    open about the tease beats looking like he forgot.\n"
            "  - CTA is 'Call or Text Me' -> tel:9055186104. Not a listing link: a link hands over "
            "    the address and kills the reason to phone him.\n"
            "\n"
            "WHEN THE PROPERTY IS NOT HIS OWN LISTING, keep the description general enough that a "
            "reader could not work out which house it is. 'Detached, three bedrooms, finished "
            "basement, high sevens' fits a hundred houses and is fine. A one-of-a-kind detail - a "
            "sauna, '$115,000 of documented upgrades', an unusual lot size - makes it findable in a "
            "minute, and at that point the email is advertising another brokerage's listing rather "
            "than advertising him."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Email subject line"},
                "preheader": {"type": "string", "description": "Short preview text shown after the subject in most inboxes", "default": ""},
                "headline": {"type": "string", "description": "Headline at the top of the email body"},
                "paragraphs": {"type": "array", "items": {"type": "string"},
                               "description": "Two to four short paragraphs of body copy"},
                "price": {"type": "string", "description": "Formatted price, e.g. $749,900", "default": ""},
                "address": {"type": "string", "description": "Property address", "default": ""},
                "features": {"type": "array", "items": {"type": "string"},
                             "description": "Short chips, two or three words max, e.g. ['3 Bed', '2.5 Bath', '1,840 sq ft']. "
                                            "They sit in a single row, so anything longer belongs in 'bullets'.", "default": []},
                "bullets": {"type": "array", "items": {"type": "string"},
                            "description": "Highlights that need a full phrase, e.g. "
                                           "['Bedroom-level laundry', 'Walking distance to downtown and GO Transit']", "default": []},
                "bullets_title": {"type": "string", "description": "Small heading above the bullets, e.g. 'Highlights'", "default": ""},
                "closing": {"type": "array", "items": {"type": "string"},
                            "description": "Copy that must appear AFTER the highlights, e.g. "
                                           "['Reply to this email and I'll send you the full details.']", "default": []},
                "cta_text": {"type": "string", "description": "Button text, e.g. 'Book a private showing'", "default": ""},
                "cta_url": {"type": "string", "description": "Where the button points - a listing page or the agent's site", "default": ""},
                "image_url": {"type": "string", "description": "Optional hero image URL for the top of the email", "default": ""},
                **SEGMENT_FIELDS,
            },
            "required": ["subject", "headline", "paragraphs"],
        },
    },
]


def _count(params: dict) -> dict:
    picked = segments.select(
        stages=params.get("stages"), sources=params.get("sources"), tags=params.get("tags"),
        cities=params.get("cities"), owner=params.get("owner"),
        exclude_stages=params.get("exclude_stages"), limit=params.get("limit"),
    )
    return {"recipients": picked["count"], "examples": picked["sample"],
            "warnings": picked["warnings"],
            "note": "Nothing built or sent. This is a count only."}


def _prepare(params: dict) -> dict:
    return campaign.prepare_deal_of_the_week(
        subject=params["subject"], headline=params["headline"],
        paragraphs=params.get("paragraphs", []), price=params.get("price", ""),
        address=params.get("address", ""), features=params.get("features", []),
        bullets=params.get("bullets", []), bullets_title=params.get("bullets_title", ""),
        closing=params.get("closing", []),
        cta_text=params.get("cta_text", ""), cta_url=params.get("cta_url", ""),
        image_url=params.get("image_url", ""), preheader=params.get("preheader", ""),
        stages=params.get("stages"), sources=params.get("sources"), tags=params.get("tags"),
        cities=params.get("cities"), owner=params.get("owner"),
        exclude_stages=params.get("exclude_stages"), limit=params.get("limit"),
    )


HANDLERS = {
    "list_crm_segments": lambda params: segments.inventory(refresh=params.get("refresh", False)),
    "count_crm_segment": _count,
    "prepare_deal_of_the_week": _prepare,
}

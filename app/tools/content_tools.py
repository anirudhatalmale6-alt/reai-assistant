from app.services import graphics

FORMAT_HINT = ("instagram_post = 1080x1080 square feed post, instagram_story = 1080x1920 "
               "vertical story/reel cover, facebook_post = 1200x630 landscape, "
               "flyer_letter = 8.5x11 printable flyer.")

TOOLS = [
    {
        "name": "create_marketing_graphic",
        "description": (
            "Design a branded marketing graphic - listing post, open house, just sold, "
            "price drop, deal of the week or printable flyer. Uses the agent's brand colours, "
            "name and contact details automatically. Returns a URL to preview the image. "
            "Always show the agent the preview link and let them approve before it is posted "
            "anywhere. Write short, punchy headlines - long ones get shrunk to fit. "
            f"Formats: {FORMAT_HINT} "
            "For the photo: pass the filename of one of the agent's uploaded photos "
            "(use list_listing_photos first to see them), or a public image URL, or 'auto' "
            "with a photo_prompt to have an image generated, or leave blank for a clean "
            "branded background. When making several sizes of the same listing, reuse the "
            "same photo so the set matches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": list(graphics.FORMATS.keys()),
                    "description": FORMAT_HINT,
                    "default": "instagram_post",
                },
                "badge": {"type": "string", "description": "Short label top-left, e.g. JUST LISTED, OPEN HOUSE, SOLD, DEAL OF THE WEEK", "default": ""},
                "headline": {"type": "string", "description": "Main hook. Keep under about 45 characters.", "default": ""},
                "price": {"type": "string", "description": "Formatted price, e.g. $749,900", "default": ""},
                "address": {"type": "string", "description": "Property address", "default": ""},
                "features": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Short selling points, e.g. ['3 Bed', '2.5 Bath', '1,840 sq ft']. Max 4 on social, 6 on a flyer.",
                    "default": [],
                },
                "cta": {"type": "string", "description": "Call to action, e.g. 'Open House Sat 2-4pm' or 'Book a private showing'", "default": ""},
                "body": {"type": "string", "description": "Longer description paragraph. Only used on flyer_letter.", "default": ""},
                "photo": {"type": "string", "description": "Uploaded filename, public image URL, 'auto' to generate, or blank", "default": ""},
                "photo_prompt": {"type": "string", "description": "What the generated photo should show (only used when photo is 'auto')", "default": ""},
            },
        },
    },
    {
        "name": "list_listing_photos",
        "description": ("List the photos the agent has uploaded, newest first, so you can pick one "
                        "for a graphic. Call this before creating a graphic whenever the agent "
                        "mentions photos they have added."),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_brand_settings",
        "description": "Show the current brand settings used on every graphic (colours, name, phone, website).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_brand_settings",
        "description": ("Update the branding applied to all graphics. Use this when the agent gives "
                        "their phone number, website, brokerage name or brand colours. Colours must "
                        "be hex like #12263A."),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Brokerage / team name"},
                "agent": {"type": "string", "description": "Agent name shown on graphics"},
                "title": {"type": "string", "description": "e.g. Sales Representative, Broker"},
                "phone": {"type": "string"},
                "website": {"type": "string"},
                "primary": {"type": "string", "description": "Main dark brand colour, hex"},
                "accent": {"type": "string", "description": "Highlight colour used for price and badges, hex"},
            },
        },
    },
]


def _graphic(params: dict) -> dict:
    return graphics.render_graphic(
        fmt=params.get("format", "instagram_post"),
        badge=params.get("badge", ""),
        headline=params.get("headline", ""),
        price=params.get("price", ""),
        address=params.get("address", ""),
        features=params.get("features", []),
        cta=params.get("cta", ""),
        body=params.get("body", ""),
        photo=params.get("photo", ""),
        photo_prompt=params.get("photo_prompt", ""),
    )


HANDLERS = {
    "create_marketing_graphic": _graphic,
    "list_listing_photos": lambda params: {"photos": graphics.list_uploads()},
    "get_brand_settings": lambda params: graphics.load_brand(),
    "update_brand_settings": lambda params: graphics.save_brand(params),
}

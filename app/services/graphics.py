"""Branded marketing graphics for listings, open houses and social posts.

Renders with Pillow only - no headless browser - so it runs comfortably on a
small VPS. Fonts are bundled in app/assets/fonts so the server needs nothing
installed system-wide.

Public entry point: render_graphic(...) -> dict with the saved file + web path.
"""
import hashlib
import json
import os
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent.parent
FONT_DIR = BASE_DIR / "assets" / "fonts"
OUT_DIR = BASE_DIR / "static" / "generated"
UPLOAD_DIR = BASE_DIR.parent / "data" / "uploads"
BRAND_FILE = BASE_DIR.parent / "data" / "brand.json"
AI_CACHE = BASE_DIR.parent / "data" / "ai_photos"
BRAND_DIR = BASE_DIR.parent / "data" / "brand"

# Every URL handed back to the chat must be absolute. A relative "/static/..."
# leaves the model to guess a host, and it guessed http://localhost:3000 - a
# dead link on the agent's phone. Same default as campaign.py.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://reai.owlhouserealty.com").rstrip("/")

OUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
BRAND_DIR.mkdir(parents=True, exist_ok=True)

# Placeholder identity until the client sends his real logo + brand colours;
# everything below reads from data/brand.json so it is a one-file change later.
DEFAULT_BRAND = {
    "name": "Owl House Realty Group",
    "agent": "Augustino Calandrino",
    "title": "Sales Representative",
    "phone": "",
    "email": "",
    "website": "",
    "primary": "#12263A",     # deep navy - panels
    "accent": "#C8A24A",      # gold - badges, rules, price
    "light": "#F5F1E8",       # warm off-white - body text on navy
    "logo": "",               # path or URL; blank = wordmark text
}

FORMATS = {
    "instagram_post": (1080, 1080, "stack"),
    "instagram_story": (1080, 1920, "stack"),
    "facebook_post": (1200, 630, "split"),
    "flyer_letter": (1275, 1650, "flyer"),
}

FONTS = {
    "display": FONT_DIR / "PlayfairDisplay-Variable.ttf",
    "sans": FONT_DIR / "Montserrat-Variable.ttf",
    "body": FONT_DIR / "Inter-Variable.ttf",
}

_font_cache: dict = {}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def load_brand() -> dict:
    brand = dict(DEFAULT_BRAND)
    if BRAND_FILE.exists():
        try:
            brand.update(json.loads(BRAND_FILE.read_text()))
        except (ValueError, OSError):
            pass
    return brand


def save_brand(updates: dict) -> dict:
    brand = load_brand()
    brand.update({k: v for k, v in updates.items() if v is not None})
    BRAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRAND_FILE.write_text(json.dumps(brand, indent=2))
    return brand


def font(kind: str, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    key = (kind, size, weight)
    if key not in _font_cache:
        f = ImageFont.truetype(str(FONTS[kind]), size)
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass  # static build of Pillow/FreeType - fall back to default weight
        _font_cache[key] = f
    return _font_cache[key]


def load_logo(brand: dict) -> Image.Image | None:
    """The agent's logo as RGBA, or None if not configured / unreadable."""
    path = (brand.get("logo") or "").strip()
    if not path:
        return None
    candidates = [Path(path), BASE_DIR.parent / path, BRAND_DIR / path]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return Image.open(candidate).convert("RGBA")
        except OSError:
            pass
    return None


def _logo_at_height(logo: Image.Image, height: int) -> Image.Image:
    ratio = logo.width / logo.height
    return logo.resize((max(1, round(height * ratio)), max(1, height)), Image.LANCZOS)


def _rgb(value: str) -> tuple:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _text_w(draw: ImageDraw.ImageDraw, text: str, fnt) -> float:
    return draw.textlength(text, font=fnt)


def _wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    """Greedy wrap on measured pixel width."""
    words, lines, line = text.split(), [], ""
    for word in words:
        probe = f"{line} {word}".strip()
        if _text_w(draw, probe, fnt) <= max_w or not line:
            line = probe
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit_headline(draw, text: str, kind: str, weight: int, max_w: int,
                  max_lines: int, start: int, floor: int) -> tuple:
    """Shrink until the headline fits in max_lines. Returns (font, lines)."""
    size = start
    while size > floor:
        fnt = font(kind, size, weight)
        lines = _wrap(draw, text, fnt, max_w)
        if len(lines) <= max_lines:
            return fnt, lines
        size -= 4
    fnt = font(kind, floor, weight)
    return fnt, _wrap(draw, text, fnt, max_w)[:max_lines]


def _cover(img: Image.Image, box: tuple) -> Image.Image:
    """Resize + centre-crop to exactly fill box (like CSS object-fit: cover)."""
    tw, th = box
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    img = img.resize((max(1, round(sw * scale)), max(1, round(sh * scale))), Image.LANCZOS)
    sw, sh = img.size
    left, top = (sw - tw) // 2, (sh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def _scrim(size: tuple, colour: tuple, start: float = 0.35, strength: int = 235) -> Image.Image:
    """Vertical transparent-to-dark gradient so text stays readable on photos."""
    w, h = size
    grad = Image.new("L", (1, h), 0)
    px = grad.load()
    for y in range(h):
        t = (y / max(1, h - 1) - start) / max(0.001, 1 - start)
        px[0, y] = 0 if t <= 0 else int(strength * (t ** 1.6))
    layer = Image.new("RGBA", (w, h), colour + (0,))
    layer.putalpha(grad.resize((w, h)))
    return layer


def _chip(draw, xy: tuple, text: str, fnt, bg: tuple, fg: tuple,
          pad: tuple = (26, 12), radius: int | None = None) -> tuple:
    """Rounded pill label. Returns its bounding box."""
    x, y = xy
    tw = _text_w(draw, text, fnt)
    asc, desc = fnt.getmetrics()
    h = asc + desc + pad[1] * 2
    w = tw + pad[0] * 2
    r = radius if radius is not None else h // 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=bg)
    draw.text((x + pad[0], y + pad[1]), text, font=fnt, fill=fg)
    return (x, y, x + w, y + h)


# --------------------------------------------------------------------------- #
# photo sourcing
# --------------------------------------------------------------------------- #
def _placeholder(box: tuple, brand: dict) -> Image.Image:
    """Branded panel used when there is no photo at all.

    Plain navy reads as a mistake, so it gets a gradient, a corner rule and a
    faint wordmark - looks deliberate rather than like a missing image.
    """
    w, h = box
    top, bottom = _rgb(brand["primary"]), tuple(max(0, c - 40) for c in _rgb(brand["primary"]))
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    img = strip.resize((w, h))

    scale = w / 1080
    accent = _rgb(brand["accent"])
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    # Prefer the real logo, faded; fall back to a faint text wordmark.
    logo = load_logo(brand)
    if logo is not None:
        art = _logo_at_height(logo, round(min(h * 0.16, (w * 0.62) / (logo.width / logo.height))))
        faded = art.copy()
        faded.putalpha(art.getchannel("A").point(lambda a: int(a * 0.30)))
        overlay.alpha_composite(faded, ((w - art.width) // 2, round(h * 0.24)))
        mark = ""
    else:
        mark = (brand.get("name") or "").upper()
    if mark:
        size = round(96 * scale)
        while size > round(30 * scale):
            fnt = font("sans", size, 800)
            if od.textlength(mark, font=fnt) <= w - round(120 * scale):
                break
            size -= 4
        fnt = font("sans", size, 800)
        tw = od.textlength(mark, font=fnt)
        od.text(((w - tw) / 2, h * 0.26), mark, font=fnt, fill=accent + (34,))

    # Thin accent corner brackets
    arm, inset, thick = round(120 * scale), round(56 * scale), max(2, round(4 * scale))

    def bar(x0, y0, x1, y1):
        od.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], fill=accent + (90,))

    # Top corners only - the bottom of this panel is where the headline sits.
    for cx, dx in ((inset, 1), (w - inset, -1)):
        bar(cx, inset, cx + arm * dx, inset + thick)      # horizontal arm
        bar(cx, inset, cx + thick * dx, inset + arm)      # vertical arm

    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img


def _generate_photo(prompt: str) -> Image.Image | None:
    """AI image when the agent has no photo of their own (no API key needed).

    Cached on disk by prompt: rendering the same listing in four sizes must not
    generate (or pay for) four different houses.
    """
    AI_CACHE.mkdir(parents=True, exist_ok=True)
    cached = AI_CACHE / f"{hashlib.sha1(prompt.encode()).hexdigest()[:16]}.png"
    if cached.is_file():
        try:
            return Image.open(cached).convert("RGB")
        except OSError:
            pass

    url = (f"https://image.pollinations.ai/prompt/{quote(prompt)}"
           f"?width=1280&height=1280&nologo=true&model=flux")
    try:
        resp = requests.get(url, timeout=75)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception:
        return None
    try:
        img.save(cached, "PNG")
    except OSError:
        pass
    return img


def resolve_photo(photo: str, box: tuple, brand: dict, photo_prompt: str = "") -> Image.Image:
    """photo may be an uploaded filename, a local path, an http(s) URL,
    'auto' to generate one from photo_prompt, or blank for a branded gradient."""
    photo = (photo or "").strip()

    if photo and photo.lower() != "auto":
        candidates = [UPLOAD_DIR / photo, Path(photo)]
        for path in candidates:
            try:
                if path.is_file():
                    return _cover(Image.open(path).convert("RGB"), box)
            except OSError:
                pass
        if photo.startswith("http"):
            try:
                resp = requests.get(photo, timeout=45)
                resp.raise_for_status()
                return _cover(Image.open(BytesIO(resp.content)).convert("RGB"), box)
            except Exception:
                pass

    if photo.lower() == "auto" or photo_prompt:
        prompt = photo_prompt or "modern suburban family home exterior, golden hour, real estate photography"
        generated = _generate_photo(prompt)
        if generated is not None:
            return _cover(generated, box)

    return _placeholder(box, brand)


# --------------------------------------------------------------------------- #
# shared blocks
# --------------------------------------------------------------------------- #
def _mls_line(img: Image.Image, d: dict, brand: dict, footer_h: int, scale: float = 1.0) -> None:
    """MLS number, small and dim, tucked just above the footer on the right.

    A listing graphic without the MLS number gives a buyer nothing to search.
    Sits outside the copy block on purpose so it can never push the call to
    action off the edge.
    """
    if not d.get("mls"):
        return
    draw = ImageDraw.Draw(img)
    w, h = img.size
    fnt = font("body", round(21 * scale), 500)
    text = f"MLS® {d['mls']}"
    light = _rgb(brand["light"])
    draw.text((w - round(48 * scale) - _text_w(draw, text, fnt),
               h - footer_h - round(34 * scale)),
              text, font=fnt, fill=tuple(int(c * 0.62) for c in light))


def _footer(img: Image.Image, brand: dict, height: int, scale: float = 1.0) -> None:
    """Accent rule + contact strip along the bottom, logo on the right."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    accent, primary, light = _rgb(brand["accent"]), _rgb(brand["primary"]), _rgb(brand["light"])
    top = h - height
    draw.rectangle([0, top, w, h], fill=primary)
    draw.rectangle([0, top, w, top + max(3, round(5 * scale))], fill=accent)

    pad = round(48 * scale)
    right = w - pad

    # Logo sits at the right edge; contact details tuck in beside it.
    logo = load_logo(brand)
    if logo is not None:
        # Wide, short wordmark: cap by width too or "REALTY GROUP" turns to mush.
        ratio = logo.width / logo.height
        mark = _logo_at_height(logo, min(round(height * 0.52), round((w * 0.32) / ratio)))
        lx, ly = right - mark.width, top + (height - mark.height) // 2 + round(4 * scale)
        img.paste(mark, (lx, ly), mark)
        right = lx - round(36 * scale)

    name_f = font("sans", round(30 * scale), 700)
    sub_f = font("body", round(23 * scale), 400)
    draw.text((pad, top + round(28 * scale)), brand["agent"] or brand["name"],
              font=name_f, fill=light)
    # The logo already carries the brokerage name, so don't repeat it there.
    sub_bits = [b for b in [brand.get("title")] if b]
    if logo is None and brand.get("name"):
        sub_bits.append(brand["name"])
    if sub_bits:
        draw.text((pad, top + round(66 * scale)), "  |  ".join(sub_bits), font=sub_f,
                  fill=tuple(int(c * 0.78) for c in light))

    contact = [b for b in [brand.get("phone"), brand.get("website")] if b]
    fnt = font("body", round(25 * scale), 600)
    y = top + (height - len(contact) * round(36 * scale)) // 2 + round(4 * scale)
    for bit in contact:
        draw.text((right - _text_w(draw, bit, fnt), y), bit, font=fnt, fill=accent)
        y += round(36 * scale)


def _features_fit(draw, features: list[str], max_w: int, scale: float) -> list[str]:
    """Keep only the features that actually fit on one line at this width."""
    fnt = font("body", round(25 * scale), 600)
    sep = round(52 * scale)  # bullet + gaps
    kept, used = [], 0.0
    for feat in features[:4]:
        w = _text_w(draw, feat, fnt) + (sep if kept else 0)
        if used + w > max_w:
            break
        kept.append(feat)
        used += w
    return kept


def _features_row(draw, x: int, y: int, features: list[str], brand: dict,
                  scale: float = 1.0) -> int:
    """beds / baths / sq ft, bullet separated. Returns the y below the row."""
    if not features:
        return y
    fnt = font("body", round(25 * scale), 600)
    light, accent = _rgb(brand["light"]), _rgb(brand["accent"])
    cx = x
    for i, feat in enumerate(features):
        if i:
            draw.text((cx, y + round(3 * scale)), "•", font=fnt, fill=accent)
            cx += round(28 * scale)
        draw.text((cx, y), feat, font=fnt, fill=light)
        cx += _text_w(draw, feat, fnt) + round(24 * scale)
    return y + round(42 * scale)


# --------------------------------------------------------------------------- #
# layouts
# --------------------------------------------------------------------------- #
def _layout_stack(size: tuple, d: dict, brand: dict) -> Image.Image:
    """Square / story: photo hero on top, dark info panel below."""
    w, h = size
    scale = w / 1080
    tall = h / w > 1.4
    panel_h = round((410 if not tall else 540) * scale)
    footer_h = round(120 * scale)
    photo_h = h - panel_h

    img = Image.new("RGB", size, _rgb(brand["primary"]))
    img.paste(resolve_photo(d.get("photo", ""), (w, photo_h), brand, d.get("photo_prompt", "")), (0, 0))
    shade = _scrim((w, photo_h), _rgb(brand["primary"]), 0.45)
    img.paste(shade, (0, 0), shade)

    draw = ImageDraw.Draw(img)
    accent, light = _rgb(brand["accent"]), _rgb(brand["light"])
    pad = round(56 * scale)

    if d.get("badge"):
        # Top RIGHT, not left. The board burns the listing brokerage's watermark
        # into the top-left of every photo it serves, so a badge there lands on
        # top of it and both come out looking like a mistake.
        chip_f = font("sans", round(26 * scale), 800)
        chip_pad = (round(30 * scale), round(14 * scale))
        chip_w = _text_w(draw, d["badge"].upper(), chip_f) + chip_pad[0] * 2
        _chip(draw, (w - pad - chip_w, pad), d["badge"].upper(), chip_f,
              accent, _rgb(brand["primary"]), chip_pad)

    # Headline sits over the bottom of the photo
    if d.get("headline"):
        fnt, lines = _fit_headline(draw, d["headline"], "display", 700, w - pad * 2,
                                   3 if tall else 2, round(76 * scale), round(40 * scale))
        line_h = round(fnt.size * 1.16)
        y = photo_h - pad - line_h * len(lines)
        for line in lines:
            draw.text((pad, y), line, font=fnt, fill=(255, 255, 255))
            y += line_h

    # Info panel - measure the block first so it sits centred in the panel
    # instead of hugging the top and pushing the call to action off the edge.
    max_w = w - pad * 2
    price_h = round(82 * scale) if d.get("price") else 0
    addr_f = font("body", round(30 * scale), 500)
    addr_lines = _wrap(draw, d["address"], addr_f, max_w)[:2] if d.get("address") else []
    feats = _features_fit(draw, d.get("features", []), max_w, scale)
    cta_f = font("sans", round(25 * scale), 700)
    cta_h = round(60 * scale) if d.get("cta") else 0
    block_h = (price_h + len(addr_lines) * round(40 * scale)
               + (round(52 * scale) if feats else 0) + cta_h)

    avail = panel_h - footer_h
    y = photo_h + max(round(30 * scale), (avail - block_h) // 2)

    if d.get("price"):
        draw.text((pad, y), d["price"], font=font("sans", round(62 * scale), 800), fill=accent)
        y += price_h
    for line in addr_lines:
        draw.text((pad, y), line, font=addr_f, fill=light)
        y += round(40 * scale)
    if feats:
        y = _features_row(draw, pad, y + round(10 * scale), feats, brand, scale)
    if d.get("cta"):
        # Clamp the chip inside the panel. An open house line like
        # "Open House Sun Aug 23, 2:00pm - 4:00pm" is long enough that the block
        # can run past the panel and jam the chip into the footer rule.
        cta_y = min(y + round(6 * scale),
                    h - footer_h - round(34 * scale) - cta_h)
        _chip(draw, (pad, cta_y), d["cta"], cta_f,
              accent, _rgb(brand["primary"]), (round(28 * scale), round(13 * scale)))

    _mls_line(img, d, brand, footer_h, scale)
    _footer(img, brand, footer_h, scale)
    return img


def _layout_split(size: tuple, d: dict, brand: dict) -> Image.Image:
    """Landscape (Facebook / link preview): photo left, copy right."""
    w, h = size
    scale = h / 630
    photo_w = round(w * 0.54)

    img = Image.new("RGB", size, _rgb(brand["primary"]))
    img.paste(resolve_photo(d.get("photo", ""), (photo_w, h), brand, d.get("photo_prompt", "")), (0, 0))

    draw = ImageDraw.Draw(img)
    accent, light = _rgb(brand["accent"]), _rgb(brand["light"])
    draw.rectangle([photo_w, 0, photo_w + round(6 * scale), h], fill=accent)

    x = photo_w + round(46 * scale)
    right = w - round(46 * scale)
    max_w = right - x
    y = round(52 * scale)

    if d.get("badge"):
        box = _chip(draw, (x, y), d["badge"].upper(), font("sans", round(21 * scale), 800),
                    accent, _rgb(brand["primary"]), (round(22 * scale), round(10 * scale)))
        y = box[3] + round(26 * scale)

    if d.get("headline"):
        fnt, lines = _fit_headline(draw, d["headline"], "display", 700, max_w, 3,
                                   round(52 * scale), round(30 * scale))
        for line in lines:
            draw.text((x, y), line, font=fnt, fill=(255, 255, 255))
            y += round(fnt.size * 1.15)
        y += round(14 * scale)

    if d.get("price"):
        pf = font("sans", round(44 * scale), 800)
        draw.text((x, y), d["price"], font=pf, fill=accent)
        y += round(60 * scale)
    if d.get("address"):
        af = font("body", round(23 * scale), 500)
        for line in _wrap(draw, d["address"], af, max_w)[:2]:
            draw.text((x, y), line, font=af, fill=light)
            y += round(32 * scale)
    feats = _features_fit(draw, d.get("features", []), max_w, scale * 0.9)
    y = _features_row(draw, x, y + round(8 * scale), feats, brand, scale * 0.9)

    if d.get("cta"):
        _chip(draw, (x, y + round(6 * scale)), d["cta"], font("sans", round(21 * scale), 700),
              accent, _rgb(brand["primary"]), (round(24 * scale), round(11 * scale)))

    _mls_line(img, d, brand, round(96 * scale), scale * 0.9)
    _footer(img, brand, round(96 * scale), scale * 0.9)
    return img


def _layout_flyer(size: tuple, d: dict, brand: dict) -> Image.Image:
    """Letter-size printable flyer: hero photo, details, description, contact."""
    w, h = size
    scale = w / 1275
    photo_h = round(h * 0.44)
    footer_h = round(150 * scale)

    img = Image.new("RGB", size, (255, 255, 255))
    img.paste(resolve_photo(d.get("photo", ""), (w, photo_h), brand, d.get("photo_prompt", "")), (0, 0))
    shade = _scrim((w, photo_h), _rgb(brand["primary"]), 0.55)
    img.paste(shade, (0, 0), shade)

    draw = ImageDraw.Draw(img)
    primary, accent = _rgb(brand["primary"]), _rgb(brand["accent"])
    ink = (28, 32, 38)
    pad = round(70 * scale)

    if d.get("badge"):
        # Top right, clear of the board's watermark - see _layout_stack.
        chip_f = font("sans", round(28 * scale), 800)
        chip_pad = (round(30 * scale), round(14 * scale))
        chip_w = _text_w(draw, d["badge"].upper(), chip_f) + chip_pad[0] * 2
        _chip(draw, (w - pad - chip_w, pad), d["badge"].upper(), chip_f,
              accent, primary, chip_pad)

    if d.get("headline"):
        fnt, lines = _fit_headline(draw, d["headline"], "display", 700, w - pad * 2, 2,
                                   round(74 * scale), round(42 * scale))
        y = photo_h - pad - round(fnt.size * 1.16) * len(lines)
        for line in lines:
            draw.text((pad, y), line, font=fnt, fill=(255, 255, 255))
            y += round(fnt.size * 1.16)

    y = photo_h + round(52 * scale)
    if d.get("price"):
        pf = font("sans", round(64 * scale), 800)
        draw.text((pad, y), d["price"], font=pf, fill=primary)
        if d.get("address"):
            af = font("body", round(27 * scale), 500)
            draw.text((pad, y + round(78 * scale)), d["address"], font=af, fill=(90, 96, 104))
        y += round(132 * scale)

    draw.rectangle([pad, y, pad + round(90 * scale), y + round(5 * scale)], fill=accent)
    y += round(34 * scale)

    for feat in d.get("features", [])[:6]:
        ff = font("body", round(26 * scale), 600)
        draw.ellipse([pad, y + round(9 * scale), pad + round(9 * scale), y + round(18 * scale)], fill=accent)
        draw.text((pad + round(26 * scale), y), feat, font=ff, fill=ink)
        y += round(40 * scale)

    if d.get("body"):
        y += round(16 * scale)
        bf = font("body", round(25 * scale), 400)
        limit = h - footer_h - round(60 * scale)
        for line in _wrap(draw, d["body"], bf, w - pad * 2):
            if y > limit:
                break
            draw.text((pad, y), line, font=bf, fill=(70, 76, 84))
            y += round(38 * scale)

    if d.get("cta"):
        _chip(draw, (pad, min(y + round(20 * scale), h - footer_h - round(76 * scale))),
              d["cta"], font("sans", round(26 * scale), 700), primary, (255, 255, 255),
              (round(30 * scale), round(14 * scale)))

    _footer(img, brand, footer_h, scale)
    return img


LAYOUTS = {"stack": _layout_stack, "split": _layout_split, "flyer": _layout_flyer}


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "graphic")).strip("-").lower()
    return (text[:40] or "graphic")


def render_graphic(fmt: str = "instagram_post", badge: str = "", headline: str = "",
                   price: str = "", address: str = "", features: list | None = None,
                   cta: str = "", body: str = "", photo: str = "",
                   photo_prompt: str = "", mls_display: str = "") -> dict:
    """Render one branded graphic. Returns the saved path + /static web path."""
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format '{fmt}'. Options: {', '.join(FORMATS)}")

    w, h, layout = FORMATS[fmt]
    brand = load_brand()
    data = {
        "badge": badge, "headline": headline, "price": price, "address": address,
        "features": [f for f in (features or []) if f], "cta": cta, "body": body,
        "photo": photo, "photo_prompt": photo_prompt, "mls": mls_display,
    }

    img = LAYOUTS[layout]((w, h), data, brand)

    stamp = hashlib.sha1(
        json.dumps({**data, "fmt": fmt}, sort_keys=True, default=str).encode()
    ).hexdigest()[:8]
    name = f"{_slug(headline or address or badge)}-{fmt}-{stamp}.png"
    out = OUT_DIR / name
    img.save(out, "PNG", optimize=True)

    return {
        "format": fmt,
        "size": f"{w}x{h}",
        "file": str(out),
        "url": f"{PUBLIC_BASE_URL}/static/generated/{name}",
        "note": "Preview it, then approve before posting anywhere. Show the agent the url "
                "field exactly as given - never rewrite the host.",
    }


def list_uploads() -> list[dict]:
    """Photos the agent has uploaded, newest first."""
    files = sorted(
        (p for p in UPLOAD_DIR.iterdir()
         if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    out = []
    for p in files[:40]:
        try:
            with Image.open(p) as im:
                dims = f"{im.width}x{im.height}"
        except OSError:
            dims = "?"
        out.append({"filename": p.name, "size": dims,
                    "url": f"{PUBLIC_BASE_URL}/api/uploads/{p.name}"})
    return out

"""Work out the order to drive a set of showings in.

Agostino's agents book showings in Supra (formerly BrokerBay) one at a time and
end up criss-crossing the city. They wanted the run ordered so it finishes near
home. Ordering by distance-from-home descending is the obvious way to do that
and it is wrong often enough to matter: with two listings on opposite sides of
town it sends the agent back and forth. What they actually want is the least
total driving with the last stop near home, and minimising the whole loop
home -> stops -> home gives exactly that, because the return leg is what pulls
the final stop inwards.

Five stops is 120 orders, so we check every one and take the best rather than
approximating. Above EXACT_LIMIT stops the factorial gets away from us and we
fall back to nearest-neighbour improved by 2-opt.

Driving times come from OSRM, not straight-line distance. That is not a detail
in Hamilton: the escarpment means two points a kilometre apart can be twenty
minutes apart by car, because you have to reach an access road up or down the
mountain. A straight-line optimiser produces a route that looks tight and
drives badly.
"""

from __future__ import annotations

import base64
import io
import itertools
import json
import math
import re
import threading
import time
import urllib.parse
from pathlib import Path

import requests

from app.config import settings

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSRM_TABLE = "https://router.project-osrm.org/table/v1/driving/"
OVERPASS = "https://overpass-api.de/api/interpreter"

#: Nominatim's usage policy asks for a real identifying User-Agent and no more
#: than one request a second. Both are honoured below - this is a free service
#: and getting blocked would take the whole feature down.
_UA = "REAI-owlhouserealty/1.0 (+https://reai.owlhouserealty.com)"
_MIN_INTERVAL = 1.1

#: Above this many stops, n! stops being something we can walk through.
#: 8! is 40,320 loops of cheap arithmetic; 9! is nine times that again.
EXACT_LIMIT = 8

CACHE_PATH = Path(settings.BASE_DIR) / "data" / "geocache.json"

_lock = threading.Lock()
_last_call = 0.0


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass  # A cache that cannot be written is slow, not broken.


def _throttle() -> None:
    global _last_call
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


#: Unit and suite numbers, which MLS and Supra put in front of the street
#: number. "202-120 Duke St" is a different place to Nominatim than
#: "120 Duke St", and "Unit 202, 120 Duke St" it cannot find at all.
_UNIT_PATTERNS = [
    r"^\s*(?:unit|suite|ste\.?|apt\.?|apartment|no\.?|#)\s*[A-Za-z]?\d+[A-Za-z]?\s*(?:[,\-–—]\s*|\s+)",
    r"^\s*[A-Za-z]?\d+[A-Za-z]?\s*[\-–—]\s*(?=\d)",
    r"\s*,?\s*(?:unit|suite|ste\.?|apt\.?|apartment)\s*[A-Za-z]?\d+[A-Za-z]?\s*$",
    r"\s*#\s*[A-Za-z]?\d+[A-Za-z]?\s*$",
]

_POSTAL = re.compile(r"[A-Za-z]\d[A-Za-z]\s*\d[A-Za-z]\d")
_HOUSE_NO = re.compile(r"^\s*(\d+)")


def strip_unit(text: str) -> str:
    """Drop a unit or suite number, keeping the street address underneath."""
    out = text
    for pattern in _UNIT_PATTERNS:
        out = re.sub(pattern, "", out, flags=re.IGNORECASE)
    return " ".join(out.split()).strip(" ,-")


def _candidates(text: str) -> list[str]:
    """The forms of an address worth asking Nominatim about, best first.

    Two rules, both learned from addresses that failed in his agent's hands:

    Only assume Hamilton when nothing else is named. The first version pinned
    "Hamilton" onto everything without a province, which quietly broke every
    Burlington and Grimsby listing - Nominatim will not resolve "Guelph Line,
    Burlington, Hamilton" and returned nothing at all. A comma means the agent
    has already told us where it is, so we say Ontario and leave it alone.

    Always try the unit-stripped form too, because "Unit 202, 120 Duke St"
    reads as having a city when it does not.

    As typed comes first, stripped second. "2-4 King St W" is a real address
    range rather than unit 2, and stripping it would send the agent next door;
    asking as typed first means a genuine range wins and only an address that
    fails or lands on the street falls through to the stripped form.
    """
    forms, seen = [], set()
    for base in (text, strip_unit(text)):
        if not base or base.lower() in seen:
            continue
        seen.add(base.lower())
        low = base.lower()
        if _POSTAL.search(base) or any(w in low for w in ("ontario", " on,", " on ", "canada")):
            forms.append(base)
        elif "," in base:
            forms.append(f"{base}, Ontario, Canada")
        else:
            # Hamilton first, so a street that exists in his own city wins.
            # Only when it does not do we widen to the province - that is what
            # rescues "1234 Guelph Line" typed with no city at all. The matched
            # line shown to the agent names the town, so a hit in Burlington
            # reads as Burlington rather than pretending to be local.
            forms.append(f"{base}, Hamilton, Ontario, Canada")
            forms.append(f"{base}, Ontario, Canada")
    return forms


def _ask(query: str) -> dict | None:
    _throttle()
    try:
        resp = requests.get(
            NOMINATIM,
            params={"format": "json", "limit": 1, "countrycodes": "ca",
                    "addressdetails": 1, "q": query},
            headers={"User-Agent": _UA},
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()
    except (requests.RequestException, ValueError):
        return None
    if not rows:
        return None

    row = rows[0]
    parts = row.get("address") or {}
    house = parts.get("house_number")
    road = parts.get("road") or parts.get("pedestrian") or ""
    town = (parts.get("city") or parts.get("town") or parts.get("village")
            or parts.get("municipality") or "")

    street = " ".join(x for x in (house, road) if x)
    short = ", ".join(x for x in (street, town) if x)
    if not street:
        short = ", ".join(p.strip() for p in row.get("display_name", query).split(",")[:2])

    return {
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "label": row.get("display_name", query),
        "short": short,
        "house": house or "",
        # No house number means it landed on the street, not the building.
        # The agent is driving to this - he needs to be told, not reassured.
        "precise": bool(house),
    }


def geocode(address: str) -> dict | None:
    """Turn a typed address into coordinates, or None if it cannot be found.

    Tries each candidate form and keeps the first that lands on the right
    building, falling back to the best near-miss so one awkward address does
    not take the whole route down.
    """
    text = " ".join((address or "").split())
    if not text:
        return None

    wanted = _HOUSE_NO.match(strip_unit(text))
    wanted_no = wanted.group(1) if wanted else None

    # v3: v2 entries predate unit stripping and the wrong-building check, so
    # serving them back would reintroduce exactly what this version fixes.
    key = f"v3|{text.lower()}"

    with _lock:
        cache = _load_cache()
        hit = cache.get(key)
        if hit:
            return {**hit, "input": text}

        best = None
        for query in _candidates(text):
            found = _ask(query)
            if not found:
                continue
            # Nominatim will happily answer 1051 Upper James with number 2741.
            # A house number that is not the one asked for is a wrong building,
            # which is worse than an honest "somewhere on this street".
            if found["house"] and wanted_no and found["house"] != wanted_no:
                found = {**found, "precise": False,
                         "short": f"{found['short']} (asked for number {wanted_no})"}
            if found["precise"]:
                best = found
                break
            best = best or found

        if not best:
            return None

        cache[key] = best
        _save_cache(cache)
        return {**best, "input": text}


def drive_matrix(points: list[dict]) -> tuple[list[list[float]], list[list[float]]] | None:
    """Driving seconds and metres between every pair of points, via OSRM."""
    coords = ";".join(f"{p['lon']},{p['lat']}" for p in points)
    try:
        resp = requests.get(
            f"{OSRM_TABLE}{coords}",
            params={"annotations": "duration,distance"},
            headers={"User-Agent": _UA},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    if data.get("code") != "Ok":
        return None

    n = len(points)
    durations = data.get("durations") or []
    distances = data.get("distances") or []
    if len(durations) != n:
        return None

    # OSRM returns null where it cannot route between two points. Treat that as
    # very expensive rather than crashing, so one bad address does not take the
    # whole run down - it just never gets picked as a neighbour.
    def clean(grid, fallback):
        return [[fallback if v is None else float(v) for v in row] for row in grid] or []

    durations = clean(durations, 9e6)
    distances = clean(distances, 9e6) if len(distances) == n else [[0.0] * n for _ in range(n)]
    return durations, distances


def find_coffee_stop(lat: float, lon: float, radius: int = 3000) -> dict | None:
    """Somewhere real to stop between two showings.

    His agent asked for a break to be suggested with an address rather than
    just a gap in the schedule, which is fair - "take fifteen minutes" is not
    much use at 7pm in an industrial park you have never been to. Searched
    around the midpoint of the two showings so it is roughly on the way, and a
    sit-down cafe wins over a drive-through when both are close.
    """
    query = (f'[out:json][timeout:25];node(around:{radius},{lat},{lon})'
             f'[amenity~"^(cafe|fast_food)$"][name];out 40;')
    try:
        resp = requests.post(OVERPASS, data={"data": query},
                             headers={"User-Agent": _UA}, timeout=40)
        resp.raise_for_status()
        elements = resp.json().get("elements") or []
    except (requests.RequestException, ValueError):
        return None  # A missing suggestion is a smaller problem than no route.

    def score(node):
        tags = node.get("tags") or {}
        away = math.hypot(node.get("lat", 0) - lat, node.get("lon", 0) - lon)
        return (0 if tags.get("amenity") == "cafe" else 1, away)

    named = [n for n in elements if (n.get("tags") or {}).get("name")]
    if not named:
        return None

    best = min(named, key=score)
    tags = best["tags"]
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    return {
        "name": tags["name"],
        "address": street,
        "maps_url": "https://www.google.com/maps/search/?" + urllib.parse.urlencode(
            {"api": "1", "query": f"{best['lat']},{best['lon']}"}),
    }


def qr_svg(url: str) -> str:
    """A QR of the route link, so the phone gets it without a copy and paste.

    He works this out on a laptop and drives with a phone, and asked for the
    hand-off to be one step. A QR needs no account, no SMS gateway and no
    typing - he points the camera at it and Maps opens.
    """
    try:
        import segno
    except ImportError:
        return ""
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=4, border=2,
                                    dark="#12263A", light="#ffffff", xmldecl=False)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _loop_cost(order: tuple[int, ...], dur: list[list[float]]) -> float:
    """Total driving for home -> stops in this order -> home. Home is index 0."""
    total = dur[0][order[0]]
    for a, b in zip(order, order[1:]):
        total += dur[a][b]
    return total + dur[order[-1]][0]


def _two_opt(order: list[int], dur: list[list[float]]) -> list[int]:
    """Repeatedly un-cross pairs of legs until no swap helps."""
    best = order[:]
    best_cost = _loop_cost(tuple(best), dur)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                trial = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                cost = _loop_cost(tuple(trial), dur)
                if cost < best_cost - 1e-9:
                    best, best_cost, improved = trial, cost, True
    return best


def best_order(dur: list[list[float]]) -> tuple[list[int], bool]:
    """Pick the stop order with the least total driving. Returns (order, exact)."""
    stops = list(range(1, len(dur)))
    if len(stops) <= 1:
        return stops, True
    if len(stops) <= EXACT_LIMIT:
        winner = min(itertools.permutations(stops), key=lambda o: _loop_cost(o, dur))
        return list(winner), True

    # Nearest neighbour from home, then 2-opt. Not provably optimal, but on a
    # city-sized run it lands within a few minutes of it.
    unvisited, order, here = set(stops), [], 0
    while unvisited:
        nxt = min(unvisited, key=lambda s: dur[here][s])
        order.append(nxt)
        unvisited.discard(nxt)
        here = nxt
    return _two_opt(order, dur), False


def _round_up(minutes: float, step: int = 15) -> int:
    return int(math.ceil(minutes / step) * step)


#: OSRM returns free-flow driving times - the road empty. His agent drives
#: these at 5pm. Without an allowance the schedule is optimistic exactly when
#: it matters, and an agent who books 30 minutes apart on free-flow times is
#: late to the second showing. These are allowances, not live traffic; live
#: traffic needs a paid API and he has not asked for that expense.
TRAFFIC = {"light": 1.0, "normal": 1.15, "rush": 1.45}
RUSH_FROM, RUSH_TO = 15 * 60, 18 * 60 + 30


def _traffic_factor(setting: str, clock: int) -> tuple[float, str]:
    key = (setting or "auto").lower()
    if key == "auto":
        key = "rush" if RUSH_FROM <= clock < RUSH_TO else "normal"
    return TRAFFIC.get(key, TRAFFIC["normal"]), key


def plan(home: str, addresses: list[str], start: str = "17:00",
         showing_minutes: int = 30, buffer_minutes: int = 5,
         traffic: str = "auto", break_after: int = 0,
         break_minutes: int = 15) -> dict:
    """Build the whole schedule: order, drive times, booking times, warnings.

    `start` is when the first showing begins, so the agent's own departure time
    is worked backwards from it - that is the number he actually needs and the
    one he would otherwise get wrong.
    """
    wanted = [a for a in (addresses or []) if a and a.strip()]
    if not home or not home.strip():
        return {"ok": False, "error": "Enter the address you're starting from."}
    if len(wanted) < 2:
        return {"ok": False, "error": "Enter at least two showing addresses."}
    if len(wanted) > 12:
        return {"ok": False, "error": "Twelve showings is the most this will take at once."}

    points, failed = [], []
    first = geocode(home)
    if not first:
        return {"ok": False, "error": f"Couldn't find that starting address: {home}"}
    points.append(first)

    for addr in wanted:
        found = geocode(addr)
        if found:
            points.append(found)
        else:
            failed.append(addr)

    if len(points) < 3:
        return {"ok": False,
                "error": "Couldn't find enough of those addresses to build a route.",
                "not_found": failed}

    matrix = drive_matrix(points)
    if not matrix:
        return {"ok": False, "error": "The mapping service didn't answer. Try again in a moment."}
    dur, dist = matrix

    try:
        hh, mm = (int(x) for x in start.split(":")[:2])
        clock = hh * 60 + mm
    except (ValueError, TypeError):
        clock = 17 * 60

    # Scaling every leg by the same factor cannot change which order is
    # shortest, so this only moves the clock, never the route.
    factor, traffic_key = _traffic_factor(traffic, clock)
    if factor != 1.0:
        dur = [[v * factor for v in row] for row in dur]

    order, exact = best_order(dur)

    def hhmm(total: int) -> str:
        total %= 24 * 60
        h, m = divmod(int(total), 60)
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {ampm}"

    leave_home = clock - _round_up(dur[0][order[0]] / 60 + buffer_minutes)

    stops, warnings, cursor, owed_break = [], [], clock, 0
    for idx, point_i in enumerate(order):
        prev = 0 if idx == 0 else order[idx - 1]
        drive = dur[prev][point_i] / 60
        if idx > 0:
            # The warning is about the drive alone. A break he asked for is not
            # a problem to warn him about, so it moves the clock but is kept out
            # of the comparison.
            gap_drive = _round_up(drive + buffer_minutes)
            cursor += showing_minutes + _round_up(drive + buffer_minutes + owed_break)
            owed_break = 0
            if gap_drive > showing_minutes:
                warnings.append(
                    f"It's {int(round(drive))} minutes from stop {idx} to stop {idx + 1}, "
                    f"so book them {showing_minutes + gap_drive} minutes apart, "
                    f"not {showing_minutes}.")
        take_break = bool(break_after) and (idx + 1) == break_after and idx + 1 < len(order)
        cursor_break, coffee = 0, None
        if take_break:
            cursor_break = cursor + showing_minutes
            owed_break = break_minutes
            here, nxt = points[point_i], points[order[idx + 1]]
            coffee = find_coffee_stop((here["lat"] + nxt["lat"]) / 2,
                                      (here["lon"] + nxt["lon"]) / 2)
        stops.append({
            "position": idx + 1,
            "address": points[point_i]["input"],
            "matched": points[point_i].get("short") or points[point_i]["label"],
            "precise": points[point_i].get("precise", True),
            "break_after": take_break,
            "break_at": hhmm(cursor_break) if take_break else "",
            "break_minutes": break_minutes if take_break else 0,
            "break_place": coffee,
            "book_at": hhmm(cursor),
            "drive_minutes": int(round(drive)),
            "drive_km": round(dist[prev][point_i] / 1000, 1),
            "from": "your starting point" if idx == 0 else f"stop {idx}",
        })

    vague = [s["address"] for s in stops if not s["precise"]]
    if vague:
        warnings.insert(0, "Couldn't pin the exact building for "
                        + ", ".join(vague)
                        + " - it used the street instead, so the times either side are rough. "
                          "Worth checking that one before you drive it.")

    home_drive = dur[order[-1]][0] / 60
    total_drive = _loop_cost(tuple(order), dur) / 60

    return {
        "ok": True,
        "exact": exact,
        "leave_at": hhmm(leave_home),
        "stops": stops,
        "finish_at": hhmm(cursor + showing_minutes),
        "home_drive_minutes": int(round(home_drive)),
        "home_at": hhmm(cursor + showing_minutes + _round_up(home_drive)),
        "total_drive_minutes": int(round(total_drive)),
        "warnings": warnings,
        "not_found": failed,
        "traffic": traffic_key,
        "traffic_note": {
            "rush": "Drive times include a rush-hour allowance, so they're "
                    "longer than an empty road.",
            "normal": "Drive times include a small allowance for normal traffic.",
            "light": "Drive times assume a clear road.",
        }.get(traffic_key, ""),
        "rush_alert": traffic_key == "rush",
        "rush_advice": (f"Rush hour. Book {showing_minutes + 15} minutes apart rather than "
                        f"{showing_minutes} if you can - the drive times below already "
                        f"allow for traffic, but it only takes one bad stretch of the QEW.")
                       if traffic_key == "rush" else "",
        "maps_url": maps_link(points, order),
        "maps_url_no_tolls": maps_link(points, order, avoid_tolls=True),
        "qr": qr_svg(maps_link(points, order)),
        # The 407 is the expensive one and it only ever appears on a run that
        # leaves town, which is exactly when his agent hit it.
        "long_run": total_drive > 45,
    }


def maps_link(points: list[dict], order: list[int], avoid_tolls: bool = False) -> str:
    """One Google Maps link with every stop already in order.

    Coordinates rather than the typed text: the agent has already seen which
    address each one matched, and a pin on the right building beats Google
    re-guessing a half-typed street name while he is driving.

    Two flavours, deliberately. The documented `api=1` form has no way to say
    "no toll roads", and on a Hamilton to Brampton run Maps happily sends him
    up the 407, which is not a road anyone drives by accident twice. The older
    `saddr`/`daddr` form still honours dirflg=t for that. It is undocumented,
    so it is offered as a second link rather than swapped in for the one that
    is already working on his agent's phone.
    """
    def pin(i: int) -> str:
        return f"{points[i]['lat']},{points[i]['lon']}"

    if avoid_tolls:
        daddr = pin(order[0])
        if len(order) > 1:
            daddr += "".join(f"+to:{pin(i)}" for i in order[1:])
        return "https://www.google.com/maps?" + urllib.parse.urlencode(
            {"saddr": pin(0), "daddr": daddr, "dirflg": "t"}, safe="+:,")

    params = {
        "api": "1",
        "origin": pin(0),
        "destination": pin(order[-1]),
        "travelmode": "driving",
    }
    if len(order) > 1:
        params["waypoints"] = "|".join(pin(i) for i in order[:-1])
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params)

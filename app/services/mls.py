"""
MLS / Realtor.ca listing search and CMA generation service.

Attempts to use the Realtor.ca API for property searches, with a
fallback to generating search URLs with map coordinates.
"""

import logging
import urllib.parse

import requests

logger = logging.getLogger(__name__)

# Realtor.ca API base URL (unofficial, may change)
REALTOR_CA_API = "https://api2.realtor.ca/Listing.svc/PropertySearch_Post"

# City center coordinates for major Ontario cities
# Used for generating map-based search URLs
CITY_COORDINATES = {
    "toronto": {"lat": 43.6532, "lng": -79.3832},
    "mississauga": {"lat": 43.5890, "lng": -79.6441},
    "brampton": {"lat": 43.7315, "lng": -79.7624},
    "hamilton": {"lat": 43.2557, "lng": -79.8711},
    "ancaster": {"lat": 43.2186, "lng": -79.9872},
    "burlington": {"lat": 43.3255, "lng": -79.7990},
    "oakville": {"lat": 43.4675, "lng": -79.6877},
    "milton": {"lat": 43.5183, "lng": -79.8774},
    "vaughan": {"lat": 43.8361, "lng": -79.4986},
    "markham": {"lat": 43.8561, "lng": -79.3370},
    "richmond hill": {"lat": 43.8828, "lng": -79.4403},
    "scarborough": {"lat": 43.7731, "lng": -79.2572},
    "etobicoke": {"lat": 43.6205, "lng": -79.5132},
    "north york": {"lat": 43.7615, "lng": -79.4111},
    "oshawa": {"lat": 43.8971, "lng": -78.8658},
    "whitby": {"lat": 43.8975, "lng": -78.9429},
    "ajax": {"lat": 43.8509, "lng": -79.0204},
    "pickering": {"lat": 43.8354, "lng": -79.0868},
    "newmarket": {"lat": 44.0592, "lng": -79.4613},
    "aurora": {"lat": 44.0065, "lng": -79.4504},
    "barrie": {"lat": 44.3894, "lng": -79.6903},
    "guelph": {"lat": 43.5448, "lng": -80.2482},
    "kitchener": {"lat": 43.4516, "lng": -80.4925},
    "waterloo": {"lat": 43.4643, "lng": -80.5204},
    "cambridge": {"lat": 43.3616, "lng": -80.3144},
    "london": {"lat": 42.9849, "lng": -81.2453},
    "windsor": {"lat": 42.3149, "lng": -83.0364},
    "ottawa": {"lat": 45.4215, "lng": -75.6972},
    "st. catharines": {"lat": 43.1594, "lng": -79.2469},
    "niagara falls": {"lat": 43.0896, "lng": -79.0849},
    "brantford": {"lat": 43.1394, "lng": -80.2644},
    "stoney creek": {"lat": 43.2175, "lng": -79.7669},
    "grimsby": {"lat": 43.1935, "lng": -79.5614},
    "dundas": {"lat": 43.2662, "lng": -79.9572},
    "caledonia": {"lat": 43.0716, "lng": -79.9533},
    "binbrook": {"lat": 43.1223, "lng": -79.8105},
}

# Property type mapping for Realtor.ca
PROPERTY_TYPE_MAP = {
    "house": 1,
    "detached": 1,
    "single family": 1,
    "semi-detached": 2,
    "semi": 2,
    "townhouse": 3,
    "town": 3,
    "row": 3,
    "condo": 5,
    "apartment": 5,
    "condo apt": 5,
    "duplex": 8,
    "triplex": 8,
    "multiplex": 8,
    "vacant land": 6,
    "land": 6,
    "farm": 7,
    "commercial": 4,
}


def search_listings(
    city: str,
    min_price: int = 0,
    max_price: int = 0,
    bedrooms: int = 0,
    property_type: str = "",
    # Aliases used by mls_tools.py
    price_min: int = 0,
    price_max: int = 0,
) -> list[dict]:
    """
    Search for property listings on Realtor.ca.

    Tries the Realtor.ca API first; if it fails, falls back to
    generating a search URL that the user can open in their browser.

    Args:
        city: City name (e.g. "Hamilton", "Toronto")
        min_price: Minimum price filter (0 = no minimum)
        max_price: Maximum price filter (0 = no maximum)
        price_min: Alias for min_price (backward compat)
        price_max: Alias for max_price (backward compat)
        bedrooms: Minimum bedrooms (0 = any)
        property_type: Property type (e.g. "house", "condo", "townhouse")

    Returns:
        List of dicts with listing details, or a single dict with a search_url fallback
    """
    # Support both parameter names
    min_price = min_price or price_min
    max_price = max_price or price_max

    # Try API search first
    try:
        results = _api_search(city, min_price, max_price, bedrooms, property_type)
        if results:
            return results
    except Exception as e:
        logger.warning("Realtor.ca API search failed, using URL fallback: %s", e)

    # Fallback: generate a search URL
    search_url = _build_realtor_url(city, min_price, max_price, bedrooms, property_type)
    return [{
        "type": "search_url",
        "message": f"I couldn't fetch listings directly. Here's a Realtor.ca search link for {city}:",
        "url": search_url,
        "city": city,
        "filters": {
            "min_price": min_price,
            "max_price": max_price,
            "bedrooms": bedrooms,
            "property_type": property_type,
        },
    }]


def _api_search(
    city: str,
    min_price: int = 0,
    max_price: int = 0,
    bedrooms: int = 0,
    property_type: str = "",
) -> list[dict]:
    """Attempt to search listings via the Realtor.ca API."""
    coords = CITY_COORDINATES.get(city.lower())
    if not coords:
        logger.warning("No coordinates for city: %s", city)
        return []

    lat, lng = coords["lat"], coords["lng"]

    # Build bounding box (~15km radius)
    lat_offset = 0.135
    lng_offset = 0.18

    form_data = {
        "ZoomLevel": "11",
        "LatitudeMax": str(lat + lat_offset),
        "LongitudeMax": str(lng + lng_offset),
        "LatitudeMin": str(lat - lat_offset),
        "LongitudeMin": str(lng - lng_offset),
        "Sort": "6-D",  # Sort by price descending
        "PropertySearchTypeId": "1",  # Residential
        "TransactionTypeId": "2",  # For sale
        "Currency": "CAD",
        "RecordsPerPage": "12",
        "CurrentPage": "1",
    }

    if min_price > 0:
        form_data["PriceMin"] = str(min_price)
    if max_price > 0:
        form_data["PriceMax"] = str(max_price)
    if bedrooms > 0:
        form_data["BedRange"] = f"{bedrooms}-0"

    if property_type:
        ptype_id = PROPERTY_TYPE_MAP.get(property_type.lower(), 0)
        if ptype_id:
            form_data["BuildingTypeId"] = str(ptype_id)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.realtor.ca/",
        "Origin": "https://www.realtor.ca",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    resp = requests.post(REALTOR_CA_API, data=form_data, headers=headers, timeout=15)
    resp.raise_for_status()

    data = resp.json()
    results = data.get("Results", [])

    listings = []
    for item in results:
        building = item.get("Building", {})
        property_info = item.get("Property", {})
        address = property_info.get("Address", {})

        price_str = property_info.get("Price", "")

        listings.append({
            "mls_number": item.get("MlsNumber", ""),
            "price": price_str,
            "address": address.get("AddressText", ""),
            "bedrooms": str(building.get("Bedrooms", "")),
            "bathrooms": str(building.get("BathroomTotal", "")),
            "property_type": building.get("Type", ""),
            "building_type": building.get("StoriesTotal", ""),
            "size_sqft": building.get("SizeInterior", ""),
            "photo_url": item.get("Property", {}).get("Photo", [{}])[0].get("HighResPath", "")
            if item.get("Property", {}).get("Photo")
            else "",
            "url": f"https://www.realtor.ca{item.get('RelativeDetailsURL', '')}",
        })

    return listings


def _build_realtor_url(
    city: str,
    min_price: int = 0,
    max_price: int = 0,
    bedrooms: int = 0,
    property_type: str = "",
) -> str:
    """
    Build a Realtor.ca map search URL with filters.

    Returns a URL like:
    https://www.realtor.ca/map#ZoomLevel=11&Center=43.255%2C-79.871&...
    """
    coords = CITY_COORDINATES.get(city.lower())
    if not coords:
        # Default to Toronto if city not found
        coords = CITY_COORDINATES["toronto"]
        logger.info("City '%s' not in coordinates lookup, defaulting to Toronto", city)

    lat, lng = coords["lat"], coords["lng"]

    lat_offset = 0.135
    lng_offset = 0.18

    params = {
        "ZoomLevel": "11",
        "Center": f"{lat}%2C{lng}",
        "LatitudeMax": f"{lat + lat_offset:.4f}",
        "LongitudeMax": f"{lng + lng_offset:.4f}",
        "LatitudeMin": f"{lat - lat_offset:.4f}",
        "LongitudeMin": f"{lng - lng_offset:.4f}",
        "Sort": "6-D",
        "PropertyTypeGroupID": "1",  # Residential
        "TransactionTypeId": "2",  # For sale
        "Currency": "CAD",
    }

    if min_price > 0:
        params["PriceMin"] = str(min_price)
    if max_price > 0:
        params["PriceMax"] = str(max_price)
    if bedrooms > 0:
        params["BedRange"] = f"{bedrooms}-0"
    if property_type:
        ptype_id = PROPERTY_TYPE_MAP.get(property_type.lower(), 0)
        if ptype_id:
            params["BuildingTypeId"] = str(ptype_id)

    # Build hash fragment (Realtor.ca uses hash-based routing)
    hash_parts = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://www.realtor.ca/map#{hash_parts}"


def generate_cma(
    address: str,
    bedrooms: int = 0,
    property_type: str = "",
) -> dict:
    """
    Generate a Comparative Market Analysis (CMA) report.

    Searches for comparable properties near the given address
    and provides a summary with price range analysis.
    """
    city = _extract_city(address)

    listings = search_listings(
        city=city,
        bedrooms=bedrooms,
        property_type=property_type,
    )

    comparables = [l for l in listings if l.get("type") != "search_url"]

    if not comparables:
        search_url = _build_realtor_url(city, bedrooms=bedrooms, property_type=property_type)
        benchmark = _get_benchmark_data(city, bedrooms, property_type)
        return {
            "address": address,
            "city": city,
            "comparables": [],
            "comparable_count": 0,
            "benchmark": benchmark,
            "search_url": search_url,
            "search_url_no_type": _build_realtor_url(city, bedrooms=bedrooms),
            "instructions": "Present a formatted CMA report using the benchmark data. Include the search links so the agent can verify with live Realtor.ca listings. Recommend they cross-reference with their MLS board access for sold data.",
        }

    prices = []
    for comp in comparables:
        price = _parse_price(comp.get("price", ""))
        if price and price > 0:
            prices.append(price)

    price_range = None
    avg_price = None
    if prices:
        price_range = {"min": min(prices), "max": max(prices)}
        avg_price = int(sum(prices) / len(prices))

    return {
        "address": address,
        "city": city,
        "comparables": comparables[:10],
        "comparable_count": len(comparables),
        "price_range": price_range,
        "avg_price": avg_price,
        "bedrooms_filter": bedrooms,
        "property_type_filter": property_type,
    }


# Ontario benchmark home prices by city and type (approximate Q2 2026)
_BENCHMARKS = {
    "toronto": {"detached": 1450000, "semi": 1050000, "townhouse": 850000, "condo": 680000},
    "hamilton": {"detached": 780000, "semi": 650000, "townhouse": 580000, "condo": 480000},
    "mississauga": {"detached": 1350000, "semi": 950000, "townhouse": 780000, "condo": 620000},
    "brampton": {"detached": 1100000, "semi": 850000, "townhouse": 720000, "condo": 550000},
    "burlington": {"detached": 1150000, "semi": 850000, "townhouse": 700000, "condo": 580000},
    "oakville": {"detached": 1600000, "semi": 1050000, "townhouse": 850000, "condo": 650000},
    "vaughan": {"detached": 1400000, "semi": 1000000, "townhouse": 820000, "condo": 600000},
    "markham": {"detached": 1350000, "semi": 980000, "townhouse": 800000, "condo": 620000},
    "richmond hill": {"detached": 1500000, "semi": 1020000, "townhouse": 830000, "condo": 610000},
    "barrie": {"detached": 720000, "semi": 580000, "townhouse": 520000, "condo": 420000},
    "kitchener": {"detached": 750000, "semi": 600000, "townhouse": 530000, "condo": 430000},
    "london": {"detached": 650000, "semi": 520000, "townhouse": 480000, "condo": 380000},
    "guelph": {"detached": 830000, "semi": 650000, "townhouse": 580000, "condo": 480000},
    "oshawa": {"detached": 780000, "semi": 620000, "townhouse": 560000, "condo": 430000},
    "ajax": {"detached": 950000, "semi": 750000, "townhouse": 650000, "condo": 520000},
    "whitby": {"detached": 950000, "semi": 730000, "townhouse": 640000, "condo": 500000},
    "pickering": {"detached": 1050000, "semi": 800000, "townhouse": 680000, "condo": 540000},
    "newmarket": {"detached": 1050000, "semi": 800000, "townhouse": 680000, "condo": 520000},
    "stoney creek": {"detached": 820000, "semi": 680000, "townhouse": 600000, "condo": 490000},
    "ancaster": {"detached": 950000, "semi": 750000, "townhouse": 650000, "condo": 520000},
    "grimsby": {"detached": 850000, "semi": 680000, "townhouse": 600000, "condo": 490000},
    "dundas": {"detached": 880000, "semi": 700000, "townhouse": 620000, "condo": 500000},
    "cambridge": {"detached": 720000, "semi": 580000, "townhouse": 520000, "condo": 420000},
    "brantford": {"detached": 620000, "semi": 500000, "townhouse": 460000, "condo": 370000},
    "milton": {"detached": 1150000, "semi": 850000, "townhouse": 720000, "condo": 560000},
    "scarborough": {"detached": 1100000, "semi": 880000, "townhouse": 750000, "condo": 560000},
    "etobicoke": {"detached": 1300000, "semi": 950000, "townhouse": 800000, "condo": 580000},
    "north york": {"detached": 1400000, "semi": 1000000, "townhouse": 820000, "condo": 620000},
}


def _get_benchmark_data(city: str, bedrooms: int, property_type: str) -> dict:
    """Get benchmark pricing data for a city/property type."""
    city_lower = city.lower()
    city_data = _BENCHMARKS.get(city_lower, _BENCHMARKS.get("hamilton"))

    ptype = property_type.lower() if property_type else ""
    type_key = "detached"
    if "semi" in ptype:
        type_key = "semi"
    elif "town" in ptype or "row" in ptype:
        type_key = "townhouse"
    elif "condo" in ptype or "apt" in ptype or "apartment" in ptype:
        type_key = "condo"
    elif ptype:
        type_key = ptype if ptype in city_data else "detached"

    base_price = city_data.get(type_key, 700000)

    bed_adj = 0
    if bedrooms:
        bed_adj = (bedrooms - 3) * int(base_price * 0.08)

    estimated = base_price + bed_adj

    return {
        "city": city,
        "property_type": type_key,
        "bedrooms": bedrooms,
        "estimated_value": estimated,
        "estimated_range_low": int(estimated * 0.92),
        "estimated_range_high": int(estimated * 1.08),
        "note": "Estimates based on Q2 2026 Ontario benchmark data. Cross-reference with MLS sold data for accuracy.",
        "all_types": {k: v for k, v in city_data.items()},
    }


def get_listing_details(mls_number: str) -> dict:
    """
    Get details for a specific MLS listing.

    Args:
        mls_number: The MLS number (e.g. "X12345678")

    Returns:
        Dict with listing details or an error/URL fallback
    """
    try:
        form_data = {
            "ReferenceNumber": mls_number,
            "PropertySearchTypeId": "1",
            "TransactionTypeId": "2",
            "Currency": "CAD",
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.realtor.ca/",
            "Origin": "https://www.realtor.ca",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        resp = requests.post(REALTOR_CA_API, data=form_data, headers=headers, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        results = data.get("Results", [])

        if not results:
            return {
                "mls_number": mls_number,
                "found": False,
                "url": f"https://www.realtor.ca/real-estate/{mls_number}",
                "message": "Listing not found via API. Try the URL above.",
            }

        item = results[0]
        building = item.get("Building", {})
        property_info = item.get("Property", {})
        address = property_info.get("Address", {})
        land = property_info.get("Land", {})

        return {
            "mls_number": item.get("MlsNumber", mls_number),
            "found": True,
            "price": property_info.get("Price", ""),
            "address": address.get("AddressText", ""),
            "city": address.get("CityDistrict", ""),
            "province": address.get("Province", ""),
            "postal_code": address.get("PostalCode", ""),
            "bedrooms": str(building.get("Bedrooms", "")),
            "bathrooms": str(building.get("BathroomTotal", "")),
            "property_type": building.get("Type", ""),
            "stories": str(building.get("StoriesTotal", "")),
            "size_sqft": building.get("SizeInterior", ""),
            "lot_size": land.get("SizeTotal", "") if land else "",
            "year_built": property_info.get("OwnershipType", ""),
            "description": property_info.get("PublicRemarks", ""),
            "url": f"https://www.realtor.ca{item.get('RelativeDetailsURL', '')}",
        }

    except Exception as e:
        logger.error("Failed to get listing details for %s: %s", mls_number, e)
        return {
            "mls_number": mls_number,
            "found": False,
            "error": str(e),
            "url": f"https://www.realtor.ca/real-estate/{mls_number}",
            "message": "Could not fetch listing details. Try the URL above.",
        }


def _extract_city(address: str) -> str:
    """
    Extract city name from an address string.
    Tries to find a known city in the address, otherwise uses
    the second-to-last comma-separated component.
    """
    address_lower = address.lower()

    # Check if any known city is in the address
    for city_name in CITY_COORDINATES:
        if city_name in address_lower:
            return city_name.title()

    # Try comma-separated parts (e.g. "123 Main St, Hamilton, ON")
    parts = [p.strip() for p in address.split(",")]
    if len(parts) >= 2:
        # The city is usually the second-to-last part
        candidate = parts[-2] if len(parts) >= 3 else parts[-1]
        return candidate.strip()

    # Default: use the whole address as-is
    return address.strip()


def _parse_price(price_str: str) -> int | None:
    """Parse a price string like '$599,000' or '599000' into an integer."""
    if not price_str:
        return None
    # Remove currency symbols, commas, spaces
    cleaned = price_str.replace("$", "").replace(",", "").replace(" ", "").strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None

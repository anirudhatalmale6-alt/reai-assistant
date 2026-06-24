"""MLS listing search and CMA tools for Claude AI."""

from app.services import mls

TOOLS = [
    {
        "name": "search_listings",
        "description": "Search for real estate listings on Realtor.ca / MLS. Can search by city, price range, bedrooms, and property type. Returns active listings with prices, addresses, and details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City to search in (required). Supports GTA cities: Toronto, Mississauga, Brampton, Vaughan, Markham, etc.",
                },
                "min_price": {
                    "type": "integer",
                    "description": "Minimum price (optional)",
                },
                "max_price": {
                    "type": "integer",
                    "description": "Maximum price (optional)",
                },
                "bedrooms": {
                    "type": "integer",
                    "description": "Number of bedrooms to filter by (optional)",
                },
                "property_type": {
                    "type": "string",
                    "description": "Type of property: detached, semi, townhouse, condo (optional)",
                },
            },
            "required": ["city"],
        },
    },
    {
        "name": "generate_cma",
        "description": "Generate a Comparative Market Analysis (CMA) report for a property. Pulls comparable listings from the area, calculates price ranges, average days on market, and suggests a listing price range. Perfect for listing presentations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "The subject property address (e.g., '45 Oakwood Drive')",
                },
                "bedrooms": {
                    "type": "integer",
                    "description": "Number of bedrooms in the subject property (helps find better comparables)",
                },
                "property_type": {
                    "type": "string",
                    "description": "Property type: detached, semi, townhouse, condo (optional)",
                },
            },
            "required": ["address"],
        },
    },
    {
        "name": "get_listing_details",
        "description": "Get full details for a specific MLS listing by its MLS number. Returns property info, description, features, photos, and more.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mls_number": {
                    "type": "string",
                    "description": "The MLS listing number (e.g., 'C1234567')",
                },
            },
            "required": ["mls_number"],
        },
    },
]

HANDLERS = {
    "search_listings": lambda params: mls.search_listings(
        city=params["city"],
        price_min=params.get("min_price", 0),
        price_max=params.get("max_price", 0),
        bedrooms=params.get("bedrooms", 0),
        property_type=params.get("property_type", ""),
    ),
    "generate_cma": lambda params: mls.generate_cma(
        address=params["address"],
        bedrooms=params.get("bedrooms", 0),
        property_type=params.get("property_type", ""),
    ),
    "get_listing_details": lambda params: mls.get_listing_details(params["mls_number"]),
}

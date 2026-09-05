"""Model Context Protocol endpoint - lets ChatGPT or Claude call REAI's tools directly.

The web chat at / was always the weak part of this project: it is a small chat box
competing with two products that have phone apps, voice, file uploads and memory.
It was never going to win, and the agent stopped opening it. This module inverts
the arrangement. Instead of REAI hosting a conversation and calling Claude, the
assistant the agent already uses every day calls REAI. The 4,700 lines of service
code - Lofty, listings, graphics, segments, the route planner - stay exactly as
they are and become tools inside ChatGPT.

Two front doors, because the two vendors expose custom tools differently and the
agent should not have to care which one he picked:

  POST /mcp            JSON-RPC 2.0, the MCP streamable-HTTP transport. This is
                       what Claude custom connectors and ChatGPT developer-mode
                       connectors speak.
  POST /gpt/call       A flat REST call, for a ChatGPT Action. Actions are the
                       older and much better trodden path on that side, so if the
                       connector route gives trouble this one still works with no
                       change to the tools themselves.

Both are the same registry and the same handlers - `_call` is the only place a
tool actually runs.

Authentication is deliberately not Caddy's basic auth. A connector UI has nowhere
to type a browser password prompt, so /mcp and /gpt are exempted in the Caddyfile
and carry their own token instead. Three ways to present it, because which one is
possible depends on the vendor's form:

  Authorization: Bearer <token>   both vendors, when the form offers an API key
  X-API-Key: <token>              some Action configurations
  POST /mcp/<token>               when the form offers no auth field at all

The last one puts a secret in a URL, which is not something to do casually - it
lands in logs and browser history. It is here because a connector that cannot be
added is worth nothing, and this endpoint reaches a real CRM: the alternative was
leaving the box unticked and the URL open to anyone who guessed the hostname.
Rotate MCP_TOKEN in .env if it is ever pasted somewhere public.

With MCP_TOKEN unset the whole surface returns 401. Closed by default is the only
safe reading of a missing secret - an empty token must never mean "no check".
"""

import json
import secrets
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.config import settings
from app.services import routing
from app.tools.registry import get_all_tools, execute_tool

router = APIRouter()

# The revision we implement. A client that asks for a different one still gets a
# working session - the methods below have been stable across revisions - so echo
# back what it asked for rather than arguing about a version neither side cares
# about at this level.
PROTOCOL_VERSION = "2025-06-18"
KNOWN_VERSIONS = {"2025-06-18", "2025-03-26", "2024-11-05"}

SERVER_INFO = {"name": "reai-owlhouserealty", "version": "1.0.0"}

# Stage one exposes only what runs on the Lofty key alone. Gmail, Calendar, Drive
# and the Facebook/Instagram tools all need an OAuth connection that is made in
# the old web UI, and a tool that is visible but always errors is worse than one
# that is absent - the assistant will keep reaching for it and keep apologising.
# They come back in stage two, once the connections are re-made from this side.
EXPOSED = {
    # Lofty CRM
    "get_crm_leads", "get_crm_lead_details", "search_crm_leads",
    "get_lead_activities", "update_crm_lead", "add_lead_note",
    "get_pipeline_summary",
    # Listings and CMA
    "search_listings", "generate_cma", "get_listing_details", "look_up_listing",
    "list_listing_photos",
    # Marketing
    "create_marketing_graphic", "get_brand_settings", "update_brand_settings",
    "prepare_deal_of_the_week",
    # Contact segments
    "list_crm_segments", "count_crm_segment",
}

# Tools that exist only here. The route planner was built as a web page and the
# agent never had a reason to open a second tab for it; as a tool it is one
# sentence inside a conversation he is already having.
ROUTE_TOOL = {
    "name": "plan_showing_route",
    "description": (
        "Work out the driving order for a set of showings so the last one finishes "
        "nearest home. Give the home address and the listing addresses; returns the "
        "order to book them in, the drive time between each, when to leave, and a "
        "Google Maps link. Uses real driving times, not straight-line distance."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "home": {"type": "string", "description": "Start and end address, usually the agent's home or office."},
            "addresses": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The showing addresses, in any order. Include the postal code where possible.",
            },
            "start": {"type": "string", "description": "First showing time, 24h HH:MM. Default 17:00."},
            "showing_minutes": {"type": "integer", "description": "Minutes spent inside each property. Default 30."},
            "buffer_minutes": {"type": "integer", "description": "Slack between showings. Default 5."},
            "traffic": {
                "type": "string",
                "description": "light, normal, rush, or auto to pick from the start time. Default auto.",
            },
        },
        "required": ["home", "addresses"],
    },
}


def _mcp_tools() -> list[dict]:
    """The Anthropic tool registry, renamed for MCP.

    The only real difference between the two schemas is input_schema vs
    inputSchema, so the registry stays the single source of truth and nothing
    has to be maintained twice.
    """
    out = []
    for tool in get_all_tools():
        if tool["name"] not in EXPOSED:
            continue
        out.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "inputSchema": tool.get("input_schema", {"type": "object", "properties": {}}),
        })
    out.append(ROUTE_TOOL)
    out.extend(_CHATGPT_TOOLS)
    return out


# ChatGPT's research-style connectors look for a tool literally called `search`
# and one called `fetch`, and will refuse to finish adding the connector without
# them. They are cheap to provide and genuinely useful on their own terms, so
# they are real tools rather than stubs that exist to satisfy a checkbox.
_CHATGPT_TOOLS = [
    {
        "name": "search",
        "description": (
            "Search across the agent's CRM contacts and listings at once. Returns "
            "matches with an id that fetch can expand. Use this when you do not know "
            "whether a name belongs to a lead or a property."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A name, address, email, phone or MLS number."}},
            "required": ["query"],
        },
    },
    {
        "name": "fetch",
        "description": "Expand one search result. Takes an id returned by search, e.g. lead:12345 or listing:X1234567.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "An id from a search result."}},
            "required": ["id"],
        },
    },
]


def _search(query: str) -> dict:
    """One query, both record types.

    Each side is caught separately. A Lofty outage should still let a listing
    lookup answer - returning nothing at all because the other half failed would
    read as "no such property", which is a different and much more misleading
    statement than "the CRM is down".
    """
    results, notes = [], []

    try:
        leads = json.loads(execute_tool("search_crm_leads", {"query": query, "limit": 10}))
        for lead in leads if isinstance(leads, list) else leads.get("leads", []):
            lead_id = lead.get("id") or lead.get("lead_id")
            if not lead_id:
                continue
            name = lead.get("name") or lead.get("full_name") or "(no name)"
            results.append({
                "id": f"lead:{lead_id}",
                "title": f"{name} - CRM contact",
                "text": ", ".join(
                    str(lead[k]) for k in ("status", "email", "phone", "source") if lead.get(k)
                ),
            })
    except Exception as e:
        notes.append(f"CRM search unavailable: {e}")

    try:
        listing = json.loads(execute_tool("look_up_listing", {"mls_number": query}))
        if isinstance(listing, dict) and not listing.get("error"):
            mls = listing.get("mls_number") or query
            results.append({
                "id": f"listing:{mls}",
                "title": f"{listing.get('address', query)} - listing",
                "text": ", ".join(
                    str(listing[k]) for k in ("price", "beds", "baths", "status") if listing.get(k)
                ),
            })
    except Exception:
        # A query that is a person's name is not a valid MLS number, and that is
        # the common case rather than an error worth reporting to the agent.
        pass

    return {"results": results, "notes": notes} if notes else {"results": results}


def _fetch(record_id: str) -> dict:
    kind, _, ident = record_id.partition(":")
    if kind == "lead":
        return json.loads(execute_tool("get_crm_lead_details", {"lead_id": ident}))
    if kind == "listing":
        return json.loads(execute_tool("get_listing_details", {"mls_number": ident}))
    return {"error": f"Unrecognised id '{record_id}'. Expected lead:<id> or listing:<mls>."}


def _call(name: str, arguments: dict) -> str:
    """Run one tool and return its JSON string. The only execution path."""
    if name == "plan_showing_route":
        plan = routing.plan(
            home=arguments["home"],
            addresses=arguments["addresses"],
            start=arguments.get("start", "17:00"),
            showing_minutes=arguments.get("showing_minutes", 30),
            buffer_minutes=arguments.get("buffer_minutes", 5),
            traffic=arguments.get("traffic", "auto"),
        )
        return json.dumps(plan, default=str, ensure_ascii=False)
    if name == "search":
        return json.dumps(_search(arguments.get("query", "")), default=str, ensure_ascii=False)
    if name == "fetch":
        return json.dumps(_fetch(arguments.get("id", "")), default=str, ensure_ascii=False)
    if name not in EXPOSED:
        return json.dumps({"error": f"Tool '{name}' is not available on this connector."})
    return execute_tool(name, arguments)


def _authorised(request: Request, path_token: str | None = None) -> bool:
    """An unset token denies everything. See the module docstring."""
    expected = settings.MCP_TOKEN
    if not expected:
        return False

    if path_token and secrets.compare_digest(path_token, expected):
        return True

    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer " and secrets.compare_digest(header[7:].strip(), expected):
        return True

    for name in ("x-api-key", "x-mcp-token"):
        supplied = request.headers.get(name)
        if supplied and secrets.compare_digest(supplied, expected):
            return True

    return False


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _handle(message: dict) -> dict | None:
    """One JSON-RPC message in, one response out - or None for a notification.

    A notification has no id and must not be answered. Returning a response to
    one puts an unmatched id on the wire and some clients treat that as a
    protocol violation and drop the session.
    """
    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}

    if req_id is None:
        return None

    if method == "initialize":
        asked = params.get("protocolVersion")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": asked if asked in KNOWN_VERSIONS else PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _mcp_tools()}}

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            payload = _call(name, arguments)
        except Exception as e:
            # A tool that blows up is a tool result the model should see and work
            # around, not a transport error. A JSON-RPC error here would end the
            # turn; isError lets the assistant explain itself and try something else.
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                    "isError": True,
                },
            }
        failed = False
        try:
            failed = isinstance(json.loads(payload), dict) and "error" in json.loads(payload)
        except (ValueError, TypeError):
            pass
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": payload}], "isError": failed},
        }

    # Prompts and resources are advertised as absent in initialize, but clients
    # probe for them anyway. -32601 is the correct, boring answer.
    return _error(req_id, -32601, f"Method not found: {method}")


async def _rpc(request: Request, path_token: str | None = None):
    if not _authorised(request, path_token):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)

    headers = {"Mcp-Session-Id": request.headers.get("mcp-session-id") or uuid.uuid4().hex}

    # A batch is a list. Notifications inside it drop out of the reply, and a
    # batch that was entirely notifications gets 202 with no body.
    if isinstance(body, list):
        replies = [r for r in (_handle(m) for m in body) if r is not None]
        if not replies:
            return Response(status_code=202, headers=headers)
        return JSONResponse(replies, headers=headers)

    reply = _handle(body)
    if reply is None:
        return Response(status_code=202, headers=headers)
    return JSONResponse(reply, headers=headers)


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    return await _rpc(request)


@router.post("/mcp/{path_token}")
async def mcp_endpoint_with_token(path_token: str, request: Request):
    return await _rpc(request, path_token)


@router.get("/mcp")
async def mcp_no_stream():
    # The transport lets a client open a GET stream for server-initiated
    # messages. This server never initiates one, and the spec says say so with
    # 405 rather than leaving the client holding a socket that will stay silent.
    return JSONResponse({"error": "This endpoint does not offer an SSE stream."}, status_code=405)


@router.delete("/mcp")
async def mcp_end_session():
    return Response(status_code=204)


# --- ChatGPT Action fallback -------------------------------------------------
# Same tools, flat REST, for when the connector form will not cooperate. A single
# call operation rather than nineteen separate ones: an Action schema is imported
# once and then frozen into the GPT, so one generic operation means adding a tool
# later does not mean he has to re-import anything.

@router.get("/gpt/tools")
async def gpt_tools(request: Request):
    if not _authorised(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"tools": _mcp_tools()}


@router.post("/gpt/call")
async def gpt_call(request: Request):
    if not _authorised(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)

    name = body.get("name")
    if not name:
        return JSONResponse({"error": "Missing 'name'."}, status_code=400)
    try:
        return json.loads(_call(name, body.get("arguments") or {}))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=200)


@router.get("/gpt/openapi.json")
async def gpt_openapi(request: Request):
    """Hand-written rather than FastAPI's generated one.

    The generated schema describes every route in the app, including the web
    UI's, and a Custom GPT would offer all of them as actions. This describes
    the two the GPT should actually use. Left unauthenticated on purpose: the
    schema has to be readable by the import step before any key is entered, and
    it is a description of the shape, not of the data.
    """
    base = str(request.base_url).rstrip("/")
    return {
        "openapi": "3.1.0",
        "info": {"title": "REAI - Owl House Realty", "version": "1.0.0",
                 "description": "Lofty CRM, listings, CMAs, marketing graphics and showing routes."},
        "servers": [{"url": base}],
        "paths": {
            "/gpt/tools": {
                "get": {
                    "operationId": "listTools",
                    "summary": "List the available tools and the arguments each one takes.",
                    "responses": {"200": {"description": "The tool list.",
                                          "content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
            "/gpt/call": {
                "post": {
                    "operationId": "callTool",
                    "summary": "Run one tool. Call listTools first if unsure of the name or arguments.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Tool name from listTools."},
                                "arguments": {"type": "object", "description": "Arguments for that tool.",
                                              "additionalProperties": True},
                            },
                            "required": ["name"],
                        }}},
                    },
                    "responses": {"200": {"description": "The tool's result.",
                                          "content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
        },
    }

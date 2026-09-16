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

import difflib
import json
import re
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
    out.append(PROFILE_TOOL)
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


PROFILE_TOOL = {
    "name": "lead_profile",
    "description": (
        "Everything about one contact in a single call: their details, and what they "
        "have been browsing and searching on the website. Use this for any question "
        "about a person - 'show me everything on X', 'what has X been looking at', "
        "'tell me about X'. Prefer this over calling search, get_crm_lead_details and "
        "get_lead_activities separately."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The person's name, email or phone number."},
            "activity_limit": {"type": "integer",
                               "description": "How many recent website actions to include. Default 15."},
        },
        "required": ["query"],
    },
}


def _lead_profile(query: str, activity_limit: int = 15) -> dict:
    """Search, open the record and pull the browsing history, in one call.

    Not a convenience wrapper - a fix for something in ChatGPT's interface. Every
    action call raises a permission box, and Agostino's build offers only Allow
    or Deny, with no way to remember the answer. Asking "show me everything on
    X" used to mean search, then details, then activities: three boxes for one
    question. Doing the three server-side makes it one.

    On an ambiguous name this deliberately stops and returns the candidates
    rather than opening the most likely one. He has a Kristina Paul and a
    Christina Paul; picking for him is how the wrong client gets phoned, and
    saving him a tap is not worth that.
    """
    found = _search(query)
    matches = found.get("results", [])
    leads = [m for m in matches if str(m.get("id", "")).startswith("lead:")]

    if not leads:
        return {"found": 0,
                "note": f"No contact matches '{query}'.",
                "other_matches": [m for m in matches if m not in leads] or None}

    if len(leads) > 1:
        return {
            "found": len(leads),
            "ambiguous": True,
            "note": ("More than one contact matches. Ask which one is meant before "
                     "acting - do not assume the first."),
            "candidates": leads,
        }

    lead_id = leads[0]["id"].split(":", 1)[1]
    profile: dict = {"found": 1}

    try:
        profile["contact"] = json.loads(execute_tool("get_crm_lead_details", {"lead_id": lead_id}))
    except Exception as e:
        profile["contact"] = {"error": str(e)}

    try:
        profile["activity"] = json.loads(execute_tool(
            "get_lead_activities", {"lead_id": lead_id, "limit": activity_limit}))
    except Exception as e:
        # The record is still worth returning without the history attached.
        profile["activity"] = []
        profile["activity_error"] = str(e)

    if found.get("notes"):
        profile["notes"] = found["notes"]
    return profile


def _arguments_schema() -> dict:
    """Name every argument the exposed tools accept, built from the tools.

    The first version typed `arguments` as a bare object with
    additionalProperties and nothing else. That reads fine to a human and is
    unusable to a model: there are no named fields, so there is nowhere obvious
    to put "Kristina Paul". His GPT duly sent `arguments: {}` twice in a row,
    got an empty result, and told him the CRM had no usable match - a confident
    wrong answer about his own contacts, produced by a schema that never asked
    for the name.

    Generated from the registry rather than written out, so a tool added later
    cannot silently go missing from here. additionalProperties stays true: the
    named list is guidance, not a whitelist.
    """
    props: dict[str, dict] = {}
    used_by: dict[str, list[str]] = {}

    for tool in _mcp_tools():
        for key, spec in ((tool.get("inputSchema") or {}).get("properties") or {}).items():
            used_by.setdefault(key, []).append(tool["name"])
            declared = spec.get("type", "string")
            if key not in props:
                props[key] = {"type": declared}
                if spec.get("items"):
                    props[key]["items"] = spec["items"]
            elif props[key]["type"] != declared:
                # Two tools disagree on the type of a shared name. A string is
                # the one shape everything survives being sent as.
                props[key] = {"type": "string"}

    for key, spec in props.items():
        tools = used_by[key]
        listed = ", ".join(tools[:4]) + (", ..." if len(tools) > 4 else "")
        spec["description"] = f"For: {listed}"

    return {
        "type": "object",
        "additionalProperties": True,
        "description": (
            "The arguments for the tool named above. Fill in the fields that tool "
            "needs - call listTools if unsure which. For a person or property "
            "lookup this is normally `query`."
        ),
        "properties": props,
    }


def _normalise_arguments(body: dict) -> dict:
    """Find the tool's arguments however the model decided to send them.

    The Action schema types `arguments` as a free-form object, and a free-form
    object is the one shape a model fills in inconsistently - there are no named
    properties to guide it. Three spellings show up in practice:

        {"name": "search", "arguments": {"query": "x"}}   what the schema asks for
        {"name": "search", "arguments": "{\\"query\\": \\"x\\"}"}  the object as a string
        {"name": "search", "query": "x"}                  arguments flattened away

    All three clearly mean the same thing, so accept all three. The alternative
    is a tool call that arrives, returns 200, finds nothing, and is reported to
    the agent as "no matching contact" - a wrong answer about his own CRM that
    looks exactly like a right one.
    """
    arguments = body.get("arguments")

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            # A bare string almost always means the one argument the tool takes.
            return {"query": arguments}

    if isinstance(arguments, dict) and arguments:
        return arguments

    # Nothing usable under `arguments` - take the top level minus the envelope.
    flattened = {k: v for k, v in body.items() if k not in ("name", "arguments")}
    return flattened or {}


# An Ontario MLS number is a letter or two and then digits (X1234567), and some
# boards use digits alone. A name never matches, which is the point.
_MLS_LIKE = re.compile(r"^[A-Za-z]{0,2}\d{5,10}[A-Za-z]?$")


def _looks_like_mls(query: str) -> bool:
    return bool(_MLS_LIKE.match(query.strip()))


def _near_matches(query: str, limit: int = 5) -> list[dict]:
    """Close-but-not-exact names from the cached contact index.

    Lofty's search wants the name spelled the way it was typed in. Agostino
    asked for "Khristina Paul"; the contact is "Kristina Paul", so the exact
    search returned nothing and he was told there was no usable match - for
    someone sitting in his own database. Agents mistype client names constantly
    and a one-letter miss should not look like an absence.

    Reads only a cache that already exists and never rebuilds one inline:
    refreshing means pulling all 8,000-odd contacts from Lofty, which is fine
    as a background job and much too slow to do inside a lookup someone is
    waiting on.

    These come back labelled as near matches, never folded in with the exact
    ones. A guess presented as a result is how the wrong client gets called.
    """
    try:
        from app.services import segments
        if not segments.CACHE_FILE.exists():
            return []
        # A huge max_age means "use whatever is cached, however old" - the
        # alternative is a rebuild the caller is blocked on.
        index = segments.load_index(max_age=10 ** 9)
    except Exception:
        return []

    by_name: dict[str, dict] = {}
    for contact in index.get("contacts") or []:
        full = f"{contact.get('first', '')} {contact.get('last', '')}".strip()
        if full:
            by_name.setdefault(full.lower(), contact)

    if not by_name:
        return []

    hits = difflib.get_close_matches(query.strip().lower(), list(by_name), n=limit, cutoff=0.72)
    return [by_name[h] for h in hits]


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

    # Exact search found nobody. Before reporting an absence - which the agent
    # will act on - check whether the name was simply mistyped.
    if not results and query.strip() and not _looks_like_mls(query):
        for contact in _near_matches(query):
            full = f"{contact.get('first', '')} {contact.get('last', '')}".strip()
            results.append({
                "id": f"lead:{contact.get('id')}",
                "title": f"{full} - CRM contact (near match, you typed '{query.strip()}')",
                "text": ", ".join(
                    str(contact[k]) for k in ("stage", "email", "phone", "source") if contact.get(k)
                ),
            })
        if results:
            notes.append(
                f"No contact is spelled '{query.strip()}'. The above are close matches on "
                f"name - confirm which one is meant before acting on it."
            )

    # Only ask the board feed about something shaped like an MLS number. The
    # first version passed every query through, so searching a person's name
    # invented a property: look_up_listing answers a miss with
    # {"found": 0, "note": ...} rather than an error key, and the guard here
    # tested for "error", so a lookup that had found nothing was read as a hit
    # and "Kristina" came back as a listing with a blank price. Agostino's
    # standing rule is never to state a property fact that isn't in the data,
    # and a search result is a property fact. Results are now built only from
    # entries inside `listings`, so a miss has nothing to build from.
    if _looks_like_mls(query):
        try:
            payload = json.loads(execute_tool("look_up_listing", {"mls_numbers": [query.strip()]}))
            for listing in payload.get("listings") or []:
                mls = listing.get("mls_number") or query.strip()
                where = ", ".join(p for p in (listing.get("address"), listing.get("city")) if p)
                results.append({
                    "id": f"listing:{mls}",
                    "title": f"{where or mls} - listing",
                    "text": ", ".join(
                        str(listing[k])
                        for k in ("price", "beds", "baths", "property_type", "status")
                        if listing.get(k)
                    ),
                })
        except Exception as e:
            notes.append(f"Listing lookup unavailable: {e}")

    return {"results": results, "notes": notes} if notes else {"results": results}


def _fetch(record_id: str) -> dict:
    kind, _, ident = record_id.partition(":")
    if kind == "lead":
        return json.loads(execute_tool("get_crm_lead_details", {"lead_id": ident}))
    if kind == "listing":
        # The board feed behind look_up_listing, not get_listing_details. The
        # latter goes to realtor.ca, which answers this server with a 403 and
        # falls back to returning a search URL - a link, not a property. Search
        # results came from the feed, so expanding one has to come from there
        # too, or the detail view would contradict the result that produced it.
        payload = json.loads(execute_tool("look_up_listing", {"mls_numbers": [ident]}))
        listings = payload.get("listings") or []
        return listings[0] if listings else {
            "error": f"No listing found for MLS {ident}.",
            "note": payload.get("note", ""),
        }
    return {"error": f"Unrecognised id '{record_id}'. Expected lead:<id> or listing:<mls>."}


def _log_call(door: str, name: str, arguments: dict, result: str = "", note: str = "") -> None:
    """One line per tool call, into the journal.

    Caddy logs the URL and the status, which is enough to answer "did ChatGPT
    reach us" and nothing more. It was not enough the first time it mattered:
    the GPT reported no match on a lead that is definitely in the CRM, both
    calls returned 200, and there was no way to see which tool it had chosen or
    what it passed. Guessing at that from the outside is how you end up fixing
    something that was never broken.

    Arguments are logged; they are short and they are the thing in question.
    Results are counted, not printed - a lead record is the agent's client data
    and it does not belong in a log to satisfy my curiosity.
    """
    size = len(result)
    count = ""
    try:
        parsed = json.loads(result) if result else None
        if isinstance(parsed, list):
            count = f" items={len(parsed)}"
        elif isinstance(parsed, dict):
            for key in ("results", "listings", "leads", "stops"):
                if isinstance(parsed.get(key), list):
                    count = f" {key}={len(parsed[key])}"
                    break
            if "error" in parsed:
                count += " ERROR"
    except (ValueError, TypeError):
        pass
    print(f"[tool] door={door} name={name!r} args={arguments!r} "
          f"bytes={size}{count}{note}", flush=True)


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
    if name == "lead_profile":
        return json.dumps(_lead_profile(arguments.get("query", ""),
                                        arguments.get("activity_limit", 15)),
                          default=str, ensure_ascii=False)
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
            _log_call("mcp", name, arguments, payload)
        except Exception as e:
            _log_call("mcp", name, arguments, note=f" EXC={e}")
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
        _log_call("gpt", "(missing)", body, note=" MISSING_NAME")
        return JSONResponse({"error": "Missing 'name'."}, status_code=400)

    arguments = _normalise_arguments(body)
    try:
        payload = _call(name, arguments)
    except Exception as e:
        _log_call("gpt", name, arguments, note=f" EXC={e}")
        return JSONResponse({"error": str(e)}, status_code=200)
    _log_call("gpt", name, arguments, payload)
    return json.loads(payload)


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
                                "arguments": _arguments_schema(),
                            },
                            "required": ["name", "arguments"],
                        }}},
                    },
                    "responses": {"200": {"description": "The tool's result.",
                                          "content": {"application/json": {"schema": {"type": "object"}}}}},
                }
            },
        },
    }

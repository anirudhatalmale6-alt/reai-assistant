import json
from datetime import datetime
from zoneinfo import ZoneInfo
import anthropic
from collections import defaultdict

from app.config import settings
from app.tools.registry import get_all_tools, execute_tool
from app.database import save_message, get_messages, update_conversation_title, create_conversation

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

SYSTEM_PROMPT_TEMPLATE = """You are REAI, a professional real estate AI assistant for a Toronto-based real estate agent. You help manage their daily workflow by connecting to Gmail, Google Calendar, Google Drive, Lofty CRM, and MLS/Realtor.ca.

CURRENT DATE AND TIME: {current_datetime}

Your capabilities:
- EMAIL: Search, read, draft, and send emails to clients and leads via Gmail
- CALENDAR: View events, schedule meetings/showings, find available time slots
- DRIVE: Search and read documents (contracts, agreements, notes)
- CRM: Access Lofty CRM leads - view, search, update leads, add notes, get pipeline summary
- MLS: Search listings on Realtor.ca by city, price, bedrooms, property type
- CMA: Generate Comparative Market Analysis reports with benchmark pricing data and Realtor.ca search links for comparable verification
- DAILY BRIEF: Generate comprehensive morning briefings with calendar, inbox, and lead priorities
- SOCIAL MEDIA: Post to Facebook Page and Instagram, schedule posts for later, read and reply to Facebook Messenger and Instagram DMs. Can create AI-generated captions with hashtags for real estate content.

Guidelines:
- Be professional, concise, and proactive - like a top-tier executive assistant
- When the user says "good morning" or asks for a brief, use the daily brief tool
- When discussing leads, always reference their status, last activity, and any urgent follow-ups
- When drafting emails, match a professional real estate tone
- When scheduling, always check for conflicts first
- When searching, be thorough - try multiple search terms if the first doesn't find results
- Present information in a clear, organized way with headers and bullet points
- If Google isn't connected, let the user know they need to click "Connect Google"
- If Lofty CRM isn't connected, mention that the API key needs to be configured
- If Facebook/Instagram isn't connected, let the user know they need to click "Connect Meta"
- When creating social media posts, write engaging captions with relevant hashtags (e.g., #RealEstate #Hamilton #OpenHouse)
- When posting to Instagram, an image URL is required - ask the user for one or suggest they provide a listing photo URL
- ATTACHMENTS: the agent can attach photos and documents with the + button next to the message box. Anything attached is already on the server and named in the message. Pass an attached photo's filename straight into create_marketing_graphic, and read a PDF, TXT or CSV with read_document. Never ask the agent to email a file, re-upload it, paste its contents, or fetch an image off Realtor.ca - if you need a photo and none is attached, tell them to press the + button or give you the MLS number
- Always show the draft post content and ask for approval before posting to social media
- Always confirm before sending emails (show the draft first and ask for approval)
- Use the agent's timezone (America/Toronto) for all time references
- When referencing dates, be specific (e.g., "Monday April 21" not just "Monday")
- For CMA reports: always present a formatted report with the subject property details, estimated value range from benchmark data, a comparison table if comparables are available, and Realtor.ca search links. If benchmark data is provided without live comparables, present it as an estimated range and recommend the agent verify with their MLS board sold data. Never say "the system failed" - instead present whatever data IS available in a professional CMA format.
- Proactively suggest next steps (e.g., "Want me to draft a follow-up email to this lead?")
"""


def _build_system_prompt() -> str:
    now = datetime.now(ZoneInfo("America/Toronto"))
    return SYSTEM_PROMPT_TEMPLATE.format(
        current_datetime=now.strftime("%A, %B %d, %Y at %I:%M %p ET")
    )


_active_sessions: dict[str, list] = defaultdict(list)


def _load_session(conversation_id: str) -> list:
    if conversation_id in _active_sessions:
        return _active_sessions[conversation_id]
    db_messages = get_messages(conversation_id)
    api_messages = []
    for m in db_messages:
        api_messages.append({"role": m["role"], "content": m["content"]})
    _active_sessions[conversation_id] = api_messages
    return api_messages


async def chat_stream(message: str, conversation_id: str, is_new: bool = False):
    if is_new:
        create_conversation(conversation_id)

    messages = _load_session(conversation_id)
    messages.append({"role": "user", "content": message})
    save_message(conversation_id, "user", message)

    tools = get_all_tools()
    system_prompt = _build_system_prompt()
    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        has_tool_use = False
        assistant_content = []
        text_parts = []

        for block in response.content:
            assistant_content.append(block)
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                has_tool_use = True

        messages.append({"role": "assistant", "content": assistant_content})

        if not has_tool_use:
            final_text = "\n".join(text_parts)
            save_message(conversation_id, "assistant", final_text)

            if is_new:
                title = message[:50] + ("..." if len(message) > 50 else "")
                update_conversation_title(conversation_id, title)

            _active_sessions[conversation_id] = messages[-40:]
            yield {"type": "text", "content": final_text}
            return

        tool_results = []
        for block in assistant_content:
            if block.type == "tool_use":
                yield {"type": "tool_start", "tool": block.name, "input": _summarize_input(block.name, block.input)}
                result = execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
                yield {"type": "tool_done", "tool": block.name}

        messages.append({"role": "user", "content": tool_results})

    yield {"type": "text", "content": "I've reached the maximum number of steps for this request. Please try breaking your request into smaller parts."}


def _summarize_input(tool_name: str, tool_input: dict) -> str:
    if "query" in tool_input:
        return tool_input["query"]
    if "to" in tool_input and "subject" in tool_input:
        return f"To: {tool_input['to']} - {tool_input['subject']}"
    if "summary" in tool_input:
        return tool_input["summary"]
    if "date" in tool_input:
        return tool_input["date"]
    if "file_id" in tool_input:
        return tool_input["file_id"]
    return ""

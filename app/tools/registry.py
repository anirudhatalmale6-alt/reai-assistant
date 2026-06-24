import json
from app.tools import gmail_tools, calendar_tools, drive_tools, lofty_tools, mls_tools, brief_tools, social_media_tools

_ALL_TOOLS = []
_ALL_HANDLERS = {}

for module in [gmail_tools, calendar_tools, drive_tools, lofty_tools, mls_tools, brief_tools, social_media_tools]:
    _ALL_TOOLS.extend(module.TOOLS)
    _ALL_HANDLERS.update(module.HANDLERS)


def get_all_tools() -> list[dict]:
    return _ALL_TOOLS


def execute_tool(name: str, params: dict) -> str:
    handler = _ALL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = handler(params)
        return json.dumps(result, default=str, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

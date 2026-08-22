"""Holding pen for social posts waiting on the agent's approval.

Nothing the assistant writes goes to Facebook or Instagram directly any more.
It drafts here; the agent presses Approve in the browser and the browser calls
the publish endpoint. That is the whole point of the design - the assistant has
no tool that publishes, so no amount of misreading "go ahead" can push a post
live on its own. The only path to Facebook runs through a human click.
"""

import json
import time
import uuid
from pathlib import Path

STORE = Path(__file__).resolve().parent.parent.parent / "data" / "pending_posts.json"
STORE.parent.mkdir(parents=True, exist_ok=True)


def _read() -> list[dict]:
    if not STORE.is_file():
        return []
    try:
        data = json.loads(STORE.read_text() or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _write(rows: list[dict]) -> None:
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2))
    tmp.replace(STORE)


def queue(platform: str, caption: str, image_url: str = "", link: str = "",
          scheduled_time: str = "") -> dict:
    """Save a draft. Returns the row, including the id the agent approves."""
    platform = (platform or "").strip().lower()
    if platform not in {"facebook", "instagram"}:
        raise ValueError("platform must be 'facebook' or 'instagram'")
    if platform == "instagram" and not image_url:
        raise ValueError("Instagram posts need an image. Make the graphic first.")

    row = {
        "id": uuid.uuid4().hex[:8],
        "platform": platform,
        "caption": caption or "",
        "image_url": image_url or "",
        "link": link or "",
        "scheduled_time": scheduled_time or "",
        "status": "pending",
        "created_at": time.time(),
    }
    rows = _read()
    rows.append(row)
    _write(rows)
    return row


def get(post_id: str) -> dict | None:
    return next((r for r in _read() if r["id"] == post_id), None)


def list_pending() -> list[dict]:
    return [r for r in _read() if r.get("status") == "pending"]


def set_status(post_id: str, status: str, result: dict | None = None) -> dict | None:
    rows = _read()
    for row in rows:
        if row["id"] == post_id:
            row["status"] = status
            row["settled_at"] = time.time()
            if result:
                row["result"] = result
            _write(rows)
            return row
    return None

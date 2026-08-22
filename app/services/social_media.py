"""Social media service for Facebook and Instagram posting, DMs, and scheduling."""

import requests
from datetime import datetime, timezone

from app.services.meta_auth import (
    get_page_token, get_page_id, get_page_name,
    get_ig_account_id, get_token_data, is_meta_connected,
)

GRAPH_API = "https://graph.facebook.com/v21.0"


def _require_connection():
    if not is_meta_connected():
        raise ValueError(
            "Facebook/Instagram is not connected yet. "
            "Please click 'Connect Meta' in the top bar to link your Facebook Page and Instagram."
        )


def create_facebook_post(message: str, link: str = "", scheduled_time: str = "",
                         image_url: str = "") -> dict:
    _require_connection()
    page_id = get_page_id()
    token = get_page_token()

    # A listing post has to BE the picture. Handing the graphic over as a link
    # got us a bare grey link card reading "reai.owlhouserealty.com" and no
    # image at all - /feed only ever renders a link preview. Photo posts go to
    # /photos with the image as `url` and the caption as `message`.
    endpoint = "photos" if image_url else "feed"
    payload = {"message": message, "access_token": token}
    if image_url:
        payload["url"] = image_url
    elif link:
        payload["link"] = link

    if scheduled_time:
        try:
            dt = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
            payload["scheduled_publish_time"] = int(dt.timestamp())
            payload["published"] = "false"
        except ValueError:
            raise ValueError(f"Invalid scheduled_time format: {scheduled_time}. Use ISO format.")

    resp = requests.post(f"{GRAPH_API}/{page_id}/{endpoint}", data=payload, timeout=20)
    if resp.status_code != 200:
        error = resp.json().get("error", {}).get("message", resp.text)
        raise ValueError(f"Facebook post failed: {error}")

    result = resp.json()
    # /photos answers with the photo id plus post_id; /feed answers with id only.
    post_id = result.get("post_id") or result.get("id", "")
    page_name = get_page_name() or "your page"

    if scheduled_time:
        return {"status": "scheduled", "post_id": post_id, "platform": "Facebook", "page": page_name, "scheduled_for": scheduled_time}
    return {"status": "posted", "post_id": post_id, "platform": "Facebook", "page": page_name, "url": f"https://www.facebook.com/{post_id}"}


def create_instagram_post(caption: str, image_url: str, scheduled_time: str = "") -> dict:
    _require_connection()
    ig_id = get_ig_account_id()
    if not ig_id:
        raise ValueError("No Instagram Business account found. Make sure your Instagram is set to Business and linked to your Facebook Page.")
    token = get_page_token()

    container_resp = requests.post(f"{GRAPH_API}/{ig_id}/media", data={
        "caption": caption, "image_url": image_url, "access_token": token,
    }, timeout=15)
    if container_resp.status_code != 200:
        error = container_resp.json().get("error", {}).get("message", container_resp.text)
        raise ValueError(f"Instagram media creation failed: {error}")

    container_id = container_resp.json().get("id")
    publish_resp = requests.post(f"{GRAPH_API}/{ig_id}/media_publish", data={
        "creation_id": container_id, "access_token": token,
    }, timeout=15)
    if publish_resp.status_code != 200:
        error = publish_resp.json().get("error", {}).get("message", publish_resp.text)
        raise ValueError(f"Instagram publish failed: {error}")

    return {"status": "posted", "media_id": publish_resp.json().get("id", ""), "platform": "Instagram"}


def get_page_posts(limit: int = 10) -> list[dict]:
    _require_connection()
    page_id = get_page_id()
    token = get_page_token()

    resp = requests.get(f"{GRAPH_API}/{page_id}/posts", params={
        "access_token": token,
        "fields": "id,message,created_time,permalink_url,shares,likes.summary(true),comments.summary(true)",
        "limit": limit,
    }, timeout=15)
    if resp.status_code != 200:
        raise ValueError("Failed to fetch Facebook posts.")

    return [{
        "id": post.get("id", ""),
        "message": post.get("message", "(no text)"),
        "created_time": post.get("created_time", ""),
        "url": post.get("permalink_url", ""),
        "likes": post.get("likes", {}).get("summary", {}).get("total_count", 0),
        "comments": post.get("comments", {}).get("summary", {}).get("total_count", 0),
        "shares": post.get("shares", {}).get("count", 0),
    } for post in resp.json().get("data", [])]


def get_page_conversations(limit: int = 10) -> list[dict]:
    _require_connection()
    page_id = get_page_id()
    token = get_page_token()

    resp = requests.get(f"{GRAPH_API}/{page_id}/conversations", params={
        "access_token": token, "fields": "id,participants,updated_time,message_count,snippet", "limit": limit,
    }, timeout=15)
    if resp.status_code != 200:
        error = resp.json().get("error", {}).get("message", resp.text)
        raise ValueError(f"Failed to fetch conversations: {error}")

    return [{
        "id": c.get("id", ""),
        "participants": [p.get("name", "") for p in c.get("participants", {}).get("data", [])],
        "last_message": c.get("snippet", ""),
        "updated_time": c.get("updated_time", ""),
        "message_count": c.get("message_count", 0),
    } for c in resp.json().get("data", [])]


def get_conversation_messages(conversation_id: str, limit: int = 10) -> list[dict]:
    _require_connection()
    token = get_page_token()

    resp = requests.get(f"{GRAPH_API}/{conversation_id}/messages", params={
        "access_token": token, "fields": "id,message,from,created_time", "limit": limit,
    }, timeout=15)
    if resp.status_code != 200:
        raise ValueError("Failed to fetch messages.")

    return [{
        "id": m.get("id", ""), "from": m.get("from", {}).get("name", ""),
        "message": m.get("message", ""), "created_time": m.get("created_time", ""),
    } for m in resp.json().get("data", [])]


def send_page_message(recipient_id: str, message: str) -> dict:
    _require_connection()
    page_id = get_page_id()
    token = get_page_token()

    resp = requests.post(f"{GRAPH_API}/{page_id}/messages", json={
        "recipient": {"id": recipient_id}, "message": {"text": message},
        "messaging_type": "RESPONSE", "access_token": token,
    }, timeout=15)
    if resp.status_code != 200:
        error = resp.json().get("error", {}).get("message", resp.text)
        raise ValueError(f"Failed to send message: {error}")

    return {"status": "sent", "recipient_id": recipient_id}


def get_ig_messages(limit: int = 10) -> list[dict]:
    _require_connection()
    ig_id = get_ig_account_id()
    if not ig_id:
        raise ValueError("No Instagram Business account connected.")
    token = get_page_token()

    resp = requests.get(f"{GRAPH_API}/{ig_id}/conversations", params={
        "access_token": token, "fields": "id,participants,updated_time,messages{id,message,from,created_time}",
        "limit": limit, "platform": "instagram",
    }, timeout=15)
    if resp.status_code != 200:
        error = resp.json().get("error", {}).get("message", resp.text)
        raise ValueError(f"Failed to fetch Instagram DMs: {error}")

    convos = []
    for c in resp.json().get("data", []):
        participants = [p.get("username", p.get("name", "")) for p in c.get("participants", {}).get("data", [])]
        msgs = [{"from": m.get("from", {}).get("username", ""), "message": m.get("message", ""), "created_time": m.get("created_time", "")}
                for m in c.get("messages", {}).get("data", [])[:5]]
        convos.append({"id": c.get("id", ""), "participants": participants, "updated_time": c.get("updated_time", ""), "recent_messages": msgs})
    return convos


def send_ig_message(recipient_id: str, message: str) -> dict:
    _require_connection()
    ig_id = get_ig_account_id()
    if not ig_id:
        raise ValueError("No Instagram Business account connected.")
    token = get_page_token()

    resp = requests.post(f"{GRAPH_API}/{ig_id}/messages", json={
        "recipient": {"id": recipient_id}, "message": {"text": message}, "access_token": token,
    }, timeout=15)
    if resp.status_code != 200:
        error = resp.json().get("error", {}).get("message", resp.text)
        raise ValueError(f"Failed to send Instagram message: {error}")

    return {"status": "sent", "recipient_id": recipient_id}

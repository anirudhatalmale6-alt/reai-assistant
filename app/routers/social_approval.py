"""Approve or discard a drafted social post.

These endpoints are called by the browser when the agent clicks a button. The
assistant cannot reach them - it has no HTTP tool - which is exactly why the
publish step lives here and not in the tool registry.
"""

from fastapi import APIRouter, HTTPException

from app.services import pending_posts, social_media

router = APIRouter()


@router.get("/pending-posts")
async def list_pending() -> dict:
    return {"pending": pending_posts.list_pending()}


@router.post("/pending-posts/{post_id}/publish")
async def publish(post_id: str) -> dict:
    row = pending_posts.get(post_id)
    if not row:
        raise HTTPException(status_code=404, detail="That draft no longer exists.")
    if row.get("status") != "pending":
        # Guard against a double click sending the same post twice.
        raise HTTPException(status_code=409,
                            detail=f"That draft was already {row.get('status')}.")

    try:
        if row["platform"] == "facebook":
            result = social_media.create_facebook_post(
                row["caption"], row.get("link", ""), row.get("scheduled_time", ""),
                row.get("image_url", ""))
        else:
            result = social_media.create_instagram_post(
                row["caption"], row["image_url"], row.get("scheduled_time", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    pending_posts.set_status(post_id, "published", result)
    return {"status": "published", "result": result}


@router.post("/pending-posts/{post_id}/discard")
async def discard(post_id: str) -> dict:
    if not pending_posts.set_status(post_id, "discarded"):
        raise HTTPException(status_code=404, detail="That draft no longer exists.")
    return {"status": "discarded"}

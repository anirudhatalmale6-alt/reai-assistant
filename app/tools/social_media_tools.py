from app.services import social_media

TOOLS = [
    {
        "name": "post_to_facebook",
        "description": "Create a post on the Facebook Business Page. Can optionally include a link and schedule for later.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The post text/caption"},
                "link": {"type": "string", "description": "Optional URL to include in the post", "default": ""},
                "scheduled_time": {"type": "string", "description": "Optional ISO datetime to schedule the post. Leave empty to post immediately.", "default": ""},
            },
            "required": ["message"],
        },
    },
    {
        "name": "post_to_instagram",
        "description": "Create a post on Instagram Business account. Requires an image URL (must be publicly accessible).",
        "input_schema": {
            "type": "object",
            "properties": {
                "caption": {"type": "string", "description": "The post caption with hashtags"},
                "image_url": {"type": "string", "description": "Public URL of the image to post"},
            },
            "required": ["caption", "image_url"],
        },
    },
    {
        "name": "get_facebook_posts",
        "description": "Get recent posts from the Facebook Page with engagement stats.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "Number of posts to retrieve", "default": 10}}},
    },
    {
        "name": "get_facebook_messages",
        "description": "Get recent Facebook Messenger conversations and DMs from the Page inbox.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "Number of conversations", "default": 10}}},
    },
    {
        "name": "read_facebook_conversation",
        "description": "Read messages in a specific Facebook Messenger conversation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "string", "description": "The conversation ID"},
                "limit": {"type": "integer", "description": "Number of messages", "default": 10},
            },
            "required": ["conversation_id"],
        },
    },
    {
        "name": "reply_facebook_message",
        "description": "Send a reply to someone in Facebook Messenger from the Page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient_id": {"type": "string", "description": "The user ID to reply to"},
                "message": {"type": "string", "description": "The message text to send"},
            },
            "required": ["recipient_id", "message"],
        },
    },
    {
        "name": "get_instagram_dms",
        "description": "Get recent Instagram Direct Message conversations.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "Number of conversations", "default": 10}}},
    },
    {
        "name": "reply_instagram_dm",
        "description": "Send a reply to someone on Instagram DMs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient_id": {"type": "string", "description": "The Instagram user ID to reply to"},
                "message": {"type": "string", "description": "The message text to send"},
            },
            "required": ["recipient_id", "message"],
        },
    },
]

HANDLERS = {
    "post_to_facebook": lambda params: social_media.create_facebook_post(params["message"], params.get("link", ""), params.get("scheduled_time", "")),
    "post_to_instagram": lambda params: social_media.create_instagram_post(params["caption"], params["image_url"], params.get("scheduled_time", "")),
    "get_facebook_posts": lambda params: social_media.get_page_posts(params.get("limit", 10)),
    "get_facebook_messages": lambda params: social_media.get_page_conversations(params.get("limit", 10)),
    "read_facebook_conversation": lambda params: social_media.get_conversation_messages(params["conversation_id"], params.get("limit", 10)),
    "reply_facebook_message": lambda params: social_media.send_page_message(params["recipient_id"], params["message"]),
    "get_instagram_dms": lambda params: social_media.get_ig_messages(params.get("limit", 10)),
    "reply_instagram_dm": lambda params: social_media.send_ig_message(params["recipient_id"], params["message"]),
}

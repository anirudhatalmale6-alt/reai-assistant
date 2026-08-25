import json
import uuid
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
from app.services.claude import chat_stream
from app.database import list_conversations, get_messages, delete_conversation

router = APIRouter()


@router.post("/chat")
async def chat(request: ChatRequest):
    is_new = request.conversation_id is None
    conversation_id = request.conversation_id or str(uuid.uuid4())

    async def event_stream():
        yield f"data: {json.dumps({'type': 'conversation_id', 'id': conversation_id})}\n\n"
        async for event in chat_stream(request.message, conversation_id, is_new=is_new):
            yield f"data: {json.dumps(event)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/conversations")
async def get_conversations(q: str | None = None):
    # Wrapped, not a bare list. The sidebar reads data.conversations, so a bare
    # array came back as undefined and every past chat was invisible - the
    # history was being saved correctly the whole time, nothing ever drew it.
    #
    # `q` searches inside the messages too, not just the titles. Titles are cut
    # from the opening line, so there are six chats called "Create a social
    # media post" and no way to tell them apart from the outside.
    return {"conversations": list_conversations(query=q)}


@router.get("/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: str):
    return {"messages": get_messages(conv_id)}


@router.delete("/conversations/{conv_id}")
async def delete_conv(conv_id: str):
    delete_conversation(conv_id)
    return {"status": "deleted"}

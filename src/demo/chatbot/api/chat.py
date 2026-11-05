"""Customer chat endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..agent.orchestrator import ConversationBusy
from ..services.common import ServiceError
from .deps import conversation_from_header, get_services, limited

router = APIRouter(prefix="/api", tags=["chat"])
_VISIBLE_ROLES = {"user", "assistant", "agent", "system"}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)


class FeedbackIn(BaseModel):
    message_id: int = Field(ge=1)
    rating: int = Field(description="1 = helpful, -1 = not helpful")
    comment: str | None = Field(default=None, max_length=500)


@router.post("/chat", dependencies=[limited("chat", "rate_limit_chat_per_minute")])
async def chat(body: ChatIn, request: Request) -> dict:
    services = get_services(request)
    if len(body.message) > services.settings.max_message_chars:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="message_too_long")
    try:
        result = await services.chat.handle(
            request.headers.get("x-conversation-token"), body.message, request.headers.get("user-agent")
        )
    except ConversationBusy as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="conversation_busy") from exc
    return result.as_dict()


@router.get("/chat/messages", dependencies=[limited("api", "rate_limit_api_per_minute")])
async def poll_messages(request: Request, after: int = Query(default=0, ge=0)) -> dict:
    services = get_services(request)
    conv_id = conversation_from_header(request)
    conversation = await services.db.run(services.conversations.get_sync, conv_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation_not_found")
    messages = await services.db.run(services.conversations.messages_after_sync, conv_id, after)
    handoff = await services.db.run(services.handoffs.status_sync, conv_id)
    return {
        "status": conversation["status"],
        "handoff": handoff,
        "messages": [
            {"id": m["id"], "role": m["role"], "content": m["content"], "created_at": m["created_at"]}
            for m in messages
            if m["role"] in _VISIBLE_ROLES
        ],
    }


@router.post("/chat/reset", dependencies=[limited("api", "rate_limit_api_per_minute")])
async def reset(request: Request) -> dict:
    services = get_services(request)
    _, token, _ = await services.chat.resolve(None, request.headers.get("user-agent"))
    return {"conversation_token": token}


@router.post("/feedback", dependencies=[limited("api", "rate_limit_api_per_minute")])
async def feedback(body: FeedbackIn, request: Request) -> dict:
    services = get_services(request)
    conv_id = conversation_from_header(request)
    try:
        result = await services.db.run(
            services.feedback.submit_sync, conv_id, body.message_id, body.rating, body.comment
        )
    except ServiceError:
        raise
    await services.analytics.record("feedback.submitted", conv_id, rating=body.rating)
    return result

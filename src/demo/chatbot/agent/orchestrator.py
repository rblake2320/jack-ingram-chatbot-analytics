"""One customer message, end to end.

1. Resolve (or create) the conversation from its signed token.
2. Take the per-conversation turn lease (cross-process); a concurrent turn gets 409.
3. Persist the user message and an analytics event (topic only, never raw text).
4. If a human agent owns the conversation, stop: the message waits for the agent.
5. Otherwise run Claude (tools) with a hard deadline; on any LLM failure fall back to the
   deterministic responder, still reporting actions the model already completed.
6. Persist the reply, append model history (append-only), emit telemetry, release the lease.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..services.common import ServiceError
from ..text import clean_text
from .fallback import FallbackResponder, brands_mentioned, classify
from .llm import LLMUnavailable
from .tools import ToolContext

if TYPE_CHECKING:
    from ..app_state import Services

log = logging.getLogger(__name__)
GENERIC_RETRY = "Sorry, I didn't catch that. Could you rephrase, or would you like me to connect you with our team?"


class ConversationBusy(Exception):
    pass


@dataclass
class ChatResult:
    conversation_token: str
    new_conversation: bool
    message_id: int | None
    reply: str | None
    source: str
    handoff: dict[str, Any] | None = None
    appointments: list[dict[str, Any]] = field(default_factory=list)
    suggest: str | None = None
    user_message_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "conversation_token": self.conversation_token,
            "new_conversation": self.new_conversation,
            "message_id": self.message_id,
            "reply": self.reply,
            "source": self.source,
            "handoff": self.handoff,
            "appointments": self.appointments,
            "suggest": self.suggest,
            "user_message_id": self.user_message_id,
        }


def _text_message(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


class ChatService:
    def __init__(self, services: Services) -> None:
        self.s = services
        self.fallback = FallbackResponder(services)

    async def resolve(self, token: str | None, user_agent: str | None) -> tuple[str, str, bool]:
        s = self.s
        conv_id = s.tokens.verify(token)
        if conv_id and await s.db.run(s.conversations.get_sync, conv_id):
            return conv_id, token or s.tokens.token_for(conv_id), False
        conv_id, token = s.tokens.issue()
        await s.db.run(s.conversations.create_sync, conv_id, user_agent)
        await s.analytics.record("conversation.started", conv_id)
        return conv_id, token, True

    def user_content(self, text: str) -> list[dict[str, Any]]:
        kb = self.s.knowledge
        now = kb.now()
        sales = "open" if kb.is_open("sales", now) else "closed"
        service = "open" if kb.is_open("service", now) else "closed"
        context = (
            f"<context>Local time at the dealership: {now:%A, %B %d, %Y, %I:%M %p} {now.tzname()}. "
            f"Sales is {sales}; service is {service}.</context>"
        )
        return [{"type": "text", "text": context}, {"type": "text", "text": text}]

    @staticmethod
    def _actions_summary(ctx: ToolContext) -> str | None:
        parts = []
        for appt in ctx.appointments:
            parts.append(f"Your {appt['label'].lower()} is booked for {appt['start_label']} "
                         f"(confirmation {appt['confirmation_code']}).")  # fmt: skip
        if ctx.leads:
            parts.append("Your request has been sent to our team; they'll be in touch soon.")
        if ctx.handoff and ctx.handoff.get("created"):
            parts.append("I've asked a member of our team to join this chat.")
        return " ".join(parts) or None

    async def handle(self, token: str | None, raw_text: str, user_agent: str | None) -> ChatResult:
        s = self.s
        text = clean_text(raw_text, max_len=s.settings.max_message_chars)
        if not text:
            raise ServiceError("Message is empty.", code="empty_message")
        conv_id, token, is_new = await self.resolve(token, user_agent)
        lease = s.settings.agent_deadline_s + 30
        if not await s.db.run(s.conversations.acquire_turn_sync, conv_id, lease):
            raise ConversationBusy(conv_id)
        try:
            return await self._turn(conv_id, token, is_new, text)
        finally:
            await s.db.run(s.conversations.release_turn_sync, conv_id)

    async def _turn(self, conv_id: str, token: str, is_new: bool, text: str) -> ChatResult:
        s = self.s
        started = time.perf_counter()
        user_message_id = await s.db.run(s.conversations.add_message_sync, conv_id, "user", text)
        await s.analytics.record("message.received", conv_id, chars=len(text), topic=classify(text),
                                 brands=brands_mentioned(text))  # fmt: skip
        conversation = await s.db.run(s.conversations.get_sync, conv_id)
        if conversation and conversation["status"] == "agent":
            handoff = await s.db.run(s.handoffs.status_sync, conv_id)
            return ChatResult(token, is_new, None, None, "agent", handoff=handoff, user_message_id=user_message_id)

        ctx = ToolContext(conversation_id=conv_id, user_texts=await s.db.run(s.conversations.user_texts_sync, conv_id),
                          services=s)  # fmt: skip
        reply: str | None = None
        source = "fallback"
        meta: dict[str, Any] = {}
        telemetry: dict[str, Any] = {}
        if s.agent.available:
            user_content = self.user_content(text)
            try:
                history = await s.db.run(s.conversations.history_sync, conv_id)
                turn = await s.agent.run(history, user_content, ctx)
                reply = turn.text or self._actions_summary(ctx) or GENERIC_RETRY
                source = "llm"
                telemetry = {**turn.usage, "model": turn.model, "refused": turn.refused,
                             "fallback_used": turn.fallback_used, "incomplete": turn.incomplete}  # fmt: skip
                new_messages = list(turn.new_messages)
                if turn.incomplete and reply:
                    if not new_messages:
                        new_messages = [{"role": "user", "content": user_content}]
                    new_messages.append(_text_message("assistant", reply))
                if new_messages or turn.replaced_history is not None:
                    await s.db.run(s.conversations.append_history_sync, conv_id, new_messages,
                                   replace=turn.replaced_history)  # fmt: skip
            except LLMUnavailable as exc:
                log.warning("LLM unavailable (%s); using fallback responder", exc.kind)
                await s.analytics.record("error", conv_id, where="llm", type=exc.kind)
                summary = self._actions_summary(ctx)
                if summary:
                    reply, source = summary, "llm_partial"
                if reply is None:
                    reply, meta = await self.fallback.respond(text, conv_id)
                await s.db.run(s.conversations.append_history_sync, conv_id,
                               [{"role": "user", "content": user_content}, _text_message("assistant", reply)])  # fmt: skip
        if reply is None:
            reply, meta = await self.fallback.respond(text, conv_id)
        handoff = ctx.handoff or meta.get("handoff") or await s.db.run(s.handoffs.status_sync, conv_id)
        message_id = await s.db.run(s.conversations.add_message_sync, conv_id, "assistant", reply, {"source": source})
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        await s.analytics.record(
            "response.sent", conv_id, latency_ms=latency_ms, source=source,
            tools=[c.name for c in ctx.tool_calls], tool_errors=sum(1 for c in ctx.tool_calls if not c.ok),
            **{k: v for k, v in telemetry.items() if k in ("input_tokens", "output_tokens", "cache_read_tokens",
                                                            "model", "refused", "fallback_used", "incomplete")},
        )  # fmt: skip
        for call in ctx.tool_calls:
            await s.analytics.record("tool.called", conv_id, name=call.name, ok=call.ok, latency_ms=call.latency_ms,
                                     error_kind=call.error_kind)  # fmt: skip
        return ChatResult(token, is_new, message_id, reply, source, handoff=handoff, appointments=ctx.appointments,
                          suggest=meta.get("suggest"), user_message_id=user_message_id)  # fmt: skip

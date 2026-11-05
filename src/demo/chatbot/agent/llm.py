"""Claude tool-use loop (Anthropic Python SDK, beta Messages API).

Why a manual loop instead of the SDK tool runner: this loop enforces a wall-clock deadline
across the whole turn, persists only complete request/response pairs (an interrupted turn
never leaves a dangling ``tool_use`` in history), records per-tool telemetry, and handles
refusal / max_tokens / pause_turn explicitly.

Request shape (claude-opus-5-5 by default):
* ``thinking={"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}``
  with beta ``thinking-binding-controls-2026-08-01``: history is append-only, and if a prefix
  ever does change the API drops stale thinking blocks instead of failing the request.
* ``output_config.effort`` set explicitly (Opus 5.5 defaults to medium).
* ``fallbacks="default"`` with beta ``server-side-fallback-2026-07-01``: a safety-classifier
  refusal is retried server-side on Anthropic's recommended fallback model.
* Top-level ``cache_control`` caches the stable tools + system + history prefix.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

from ..resilience import CircuitBreaker
from ..services.conversations import strip_thinking
from .tools import ToolContext, ToolSpec, execute_tool, to_tool_result

log = logging.getLogger(__name__)

THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
REFUSAL_TEXT = (
    "I'm not able to help with that request here. I can help with vehicles, pricing, service and appointments, "
    "or connect you with a member of our team."
)
_DROP_BEFORE_FALLBACK = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}


class LLMUnavailable(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass
class AgentTurn:
    text: str
    new_messages: list[dict[str, Any]]
    usage: dict[str, int] = field(default_factory=dict)
    model: str | None = None
    stop_reason: str | None = None
    refused: bool = False
    fallback_used: bool = False
    incomplete: bool = False
    replaced_history: list[dict[str, Any]] | None = None


def _block_to_param(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True, by_alias=True)
    return dict(block)


def response_content(blocks: list[Any]) -> list[dict[str, Any]]:
    """Content to echo back. After a server-side fallback boundary, only text survives from before it."""
    params = [_block_to_param(b) for b in blocks]
    boundary = max((i for i, b in enumerate(params) if b.get("type") == "fallback"), default=-1)
    out = []
    for index, block in enumerate(params):
        kind = block.get("type")
        if kind == "fallback":
            continue
        if index < boundary and kind in _DROP_BEFORE_FALLBACK:
            continue
        out.append(block)
    return out


def _has_thinking(messages: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(m.get("content"), list)
        and any(b.get("type") in ("thinking", "redacted_thinking") for b in m["content"])
        for m in messages
    )


class ClaudeAgent:
    def __init__(
        self,
        client: Any,
        *,
        model: str,
        effort: str,
        max_tokens: int,
        max_iterations: int,
        deadline_s: float,
        refusal_fallbacks: bool,
        system_prompt: str,
        tools: list[ToolSpec],
    ) -> None:
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations
        self.deadline_s = deadline_s
        self.refusal_fallbacks = refusal_fallbacks
        self.system_prompt = system_prompt
        self.tools = {t.name: t for t in tools}
        self.tool_defs = [t.definition() for t in tools]
        self.breaker = CircuitBreaker("anthropic", threshold=3, reset_after_s=60)

    @property
    def available(self) -> bool:
        return self.client is not None and self.breaker.allow()

    def request_kwargs(self, messages: list[dict[str, Any]], *, final: bool) -> dict[str, Any]:
        betas = [THINKING_BINDING_BETA]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": self.system_prompt}],
            "tools": self.tool_defs,
            "messages": messages,
            "thinking": {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
            "output_config": {"effort": self.effort},
            "cache_control": {"type": "ephemeral"},
        }
        if final:
            kwargs["tool_choice"] = {"type": "none"}
        if self.refusal_fallbacks:
            kwargs["fallbacks"] = "default"
            betas.append(FALLBACK_BETA)
        kwargs["betas"] = betas
        return kwargs

    async def _create(self, messages: list[dict[str, Any]], *, final: bool, timeout: float) -> Any:
        try:
            response = await asyncio.wait_for(
                self.client.beta.messages.create(**self.request_kwargs(messages, final=final)), timeout=timeout
            )
        except TimeoutError as exc:
            self.breaker.record_failure()
            raise LLMUnavailable("timeout") from exc
        except anthropic.BadRequestError:
            raise
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            for _ in range(self.breaker.threshold):
                self.breaker.record_failure()
            log.error("Claude credentials rejected (%s); falling back", type(exc).__name__)
            raise LLMUnavailable("auth") from exc
        except anthropic.RateLimitError as exc:
            self.breaker.record_failure()
            raise LLMUnavailable("rate_limited") from exc
        except anthropic.APIStatusError as exc:
            self.breaker.record_failure()
            log.warning("Claude API error HTTP %s", exc.status_code)
            raise LLMUnavailable("upstream_error") from exc
        except anthropic.APIConnectionError as exc:
            self.breaker.record_failure()
            raise LLMUnavailable("connection") from exc
        self.breaker.record_success()
        return response

    async def run(
        self, history: list[dict[str, Any]], user_content: list[dict[str, Any]], ctx: ToolContext
    ) -> AgentTurn:
        if self.client is None:
            raise LLMUnavailable("not_configured")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.deadline_s
        base_history = list(history)
        user_message = {"role": "user", "content": user_content}
        pending: list[dict[str, Any]] = [user_message]  # appended to history only when complete
        committed: list[dict[str, Any]] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
        turn = AgentTurn(text="", new_messages=[], usage=usage)
        stripped = False
        iteration = 0
        while iteration < self.max_iterations:
            remaining = deadline - loop.time()
            if remaining <= 1:
                raise LLMUnavailable("deadline")
            final = iteration == self.max_iterations - 1
            messages = base_history + committed + pending
            try:
                response = await self._create(messages, final=final, timeout=remaining)
            except anthropic.BadRequestError as exc:
                if not stripped and _has_thinking(base_history + committed):
                    # One-time recovery (documented): drop thinking blocks and retry once.
                    log.warning("Claude rejected history (%s); retrying without thinking blocks", exc.status_code)
                    base_history = strip_thinking(base_history)
                    committed = strip_thinking(committed)
                    turn.replaced_history = base_history
                    stripped = True
                    continue
                self.breaker.record_failure()
                log.error("Claude rejected request: %s", getattr(exc, "message", exc))
                raise LLMUnavailable("bad_request") from exc
            iteration += 1
            u = response.usage
            usage["input_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
            usage["output_tokens"] += int(getattr(u, "output_tokens", 0) or 0)
            usage["cache_read_tokens"] += int(getattr(u, "cache_read_input_tokens", 0) or 0)
            usage["cache_write_tokens"] += int(getattr(u, "cache_creation_input_tokens", 0) or 0)
            if any(getattr(it, "type", None) == "fallback_message" for it in (getattr(u, "iterations", None) or [])):
                turn.fallback_used = True
            turn.model = getattr(response, "model", None)
            turn.stop_reason = response.stop_reason
            content = response_content(list(response.content))

            if response.stop_reason == "refusal":
                turn.refused = True
                turn.text = REFUSAL_TEXT
                turn.new_messages = committed  # never persist the refused exchange
                return turn

            assistant = {"role": "assistant", "content": content}
            tool_uses = [b for b in content if b.get("type") == "tool_use"]

            if response.stop_reason == "tool_use" and tool_uses and not final:
                outcomes = await asyncio.gather(
                    *(execute_tool(self.tools.get(b["name"]), b["name"], b.get("input"), ctx) for b in tool_uses)
                )
                results = [
                    to_tool_result(b["id"], payload, err) for b, (payload, err) in zip(tool_uses, outcomes, strict=True)
                ]
                committed = committed + pending + [assistant, {"role": "user", "content": results}]
                pending = []
                continue

            if response.stop_reason == "pause_turn":
                committed = committed + pending + [assistant]
                pending = []
                continue

            text = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            if tool_uses or response.stop_reason == "max_tokens":
                # Truncated or unexpected tool call: keep completed work, drop the partial message.
                turn.incomplete = True
                turn.text = text
                turn.new_messages = committed + pending if not tool_uses else committed or []
                if tool_uses and not committed:
                    turn.new_messages = []
                return turn

            turn.text = text
            turn.new_messages = committed + pending + [assistant]
            return turn
        turn.incomplete = True
        turn.new_messages = committed
        return turn

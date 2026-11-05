"""Perplexity Sonar web answers (optional, key-gated) for questions that need the live web."""

from __future__ import annotations

from typing import Any

import httpx

from ..cache import Cache
from ..ledger import fingerprint
from ..resilience import CircuitBreaker, UpstreamError, request_json

ANSWER_TTL = 900
_SYSTEM = (
    "You answer questions for customers of Jack Ingram Motors in Montgomery, Alabama. "
    "Be concise and factual, cite sources, and say plainly when you cannot find current information."
)


class PerplexityClient:
    def __init__(self, http: httpx.AsyncClient, cache: Cache, *, api_key: str | None, api_url: str, model: str):
        self.http = http
        self.cache = cache
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.breaker = CircuitBreaker("perplexity", threshold=3, reset_after_s=60)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def ask(self, question: str) -> dict[str, Any]:
        if not self.configured:
            raise UpstreamError("perplexity", "not_configured")
        question = question.strip()[:500]
        key = f"perplexity:{self.model}:{fingerprint(question.lower())}"
        cached = await self.cache.get(key)
        if cached is not None:
            return cached
        data = await request_json(
            self.http,
            "POST",
            self.api_url,
            upstream="perplexity",
            breaker=self.breaker,
            json_body={
                "model": self.model,
                "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": question}],
                "max_tokens": 600,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=25.0,
            attempts=2,
        )
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("perplexity", "bad_response", "no answer in response") from exc
        citations = data.get("citations") or [r.get("url") for r in data.get("search_results") or [] if r.get("url")]
        result = {"answer": str(answer)[:4000], "citations": list(citations)[:8], "untrusted_content": True}
        await self.cache.set(key, result, ANSWER_TTL)
        return result

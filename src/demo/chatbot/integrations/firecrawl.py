"""FireCrawl scraping of the dealership's own specials pages (optional, key-gated).

Only URLs listed in SPECIALS_URLS are ever fetched, so neither the model nor a user can turn
this into an open proxy (SSRF). Scraped text is untrusted and is returned as data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ..cache import Cache
from ..resilience import CircuitBreaker, UpstreamError, request_json

SCRAPE_TTL = 3600
MAX_CHARS_PER_PAGE = 6000


class FirecrawlClient:
    def __init__(
        self, http: httpx.AsyncClient, cache: Cache, *, api_key: str | None, api_url: str, urls: list[str]
    ) -> None:
        self.http = http
        self.cache = cache
        self.api_key = api_key
        self.api_url = api_url
        self.urls = list(urls)
        self.breaker = CircuitBreaker("firecrawl", threshold=3, reset_after_s=120)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.urls)

    async def scrape(self, url: str) -> dict[str, Any]:
        if not self.configured:
            raise UpstreamError("firecrawl", "not_configured")
        if url not in self.urls:
            raise ValueError("URL is not an allow-listed specials page")
        key = f"firecrawl:{url}"
        cached = await self.cache.get(key)
        if cached is not None:
            return cached
        data = await request_json(
            self.http,
            "POST",
            self.api_url,
            upstream="firecrawl",
            breaker=self.breaker,
            json_body={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
            attempts=2,
        )
        doc = data.get("data", data) if isinstance(data, dict) else {}
        markdown = doc.get("markdown") if isinstance(doc, dict) else None
        if not isinstance(markdown, str) or not markdown.strip():
            raise UpstreamError("firecrawl", "bad_response", "no markdown in response")
        result = {
            "url": url,
            "content": markdown[:MAX_CHARS_PER_PAGE],
            "truncated": len(markdown) > MAX_CHARS_PER_PAGE,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        await self.cache.set(key, result, SCRAPE_TTL)
        return result

    async def specials(self, limit: int = 3) -> dict[str, Any]:
        pages, errors = [], []
        for url in self.urls[:limit]:
            try:
                pages.append(await self.scrape(url))
            except (UpstreamError, ValueError) as exc:
                errors.append({"url": url, "error": getattr(exc, "kind", "invalid")})
        return {"pages": pages, "errors": errors, "untrusted_content": True}

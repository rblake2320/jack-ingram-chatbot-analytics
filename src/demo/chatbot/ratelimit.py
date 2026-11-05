"""Fixed-window rate limiter stored in SQLite, so the limit holds across all worker processes."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .db import Database


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    count: int
    limit: int
    retry_after_s: int


class RateLimiter:
    def __init__(self, db: Database, *, clock=time.time) -> None:
        self.db = db
        self.clock = clock

    def hit_sync(self, bucket: str, limit: int, window_s: int) -> RateDecision:
        now = self.clock()
        window_start = int(now // window_s) * window_s
        with self.db.tx(durable=False) as conn:
            row = conn.execute(
                "INSERT INTO rate_limits (bucket, window_start, count) VALUES (?, ?, 1)"
                " ON CONFLICT (bucket, window_start) DO UPDATE SET count = count + 1"
                " RETURNING count",
                (bucket, window_start),
            ).fetchone()
        count = int(row[0])
        retry = max(1, int(window_start + window_s - now) + 1)
        return RateDecision(allowed=count <= limit, count=count, limit=limit, retry_after_s=retry)

    async def hit(self, bucket: str, limit: int, window_s: int) -> RateDecision:
        return await self.db.run(self.hit_sync, bucket, limit, window_s)

    def purge_sync(self, older_than_s: int = 7200) -> int:
        cutoff = int(self.clock()) - older_than_s
        with self.db.tx(durable=False) as conn:
            return conn.execute("DELETE FROM rate_limits WHERE window_start < ?", (cutoff,)).rowcount

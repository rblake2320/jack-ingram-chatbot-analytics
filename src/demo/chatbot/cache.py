"""Shared TTL cache (SQLite) for upstream API responses; survives restarts, shared by workers."""

from __future__ import annotations

import json
import time
from typing import Any

from .db import Database


class Cache:
    def __init__(self, db: Database, *, clock=time.time) -> None:
        self.db = db
        self.clock = clock

    def get_sync(self, key: str) -> Any | None:
        with self.db.read() as conn:
            row = conn.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,)).fetchone()
        if row is None or row["expires_at"] <= self.clock():
            return None
        try:
            return json.loads(row["value"])
        except ValueError:
            return None

    def set_sync(self, key: str, value: Any, ttl_s: float) -> None:
        with self.db.tx(durable=False) as conn:
            conn.execute(
                "INSERT INTO cache (key, value, expires_at) VALUES (?, ?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at",
                (key, json.dumps(value, default=str), self.clock() + ttl_s),
            )

    async def get(self, key: str) -> Any | None:
        return await self.db.run(self.get_sync, key)

    async def set(self, key: str, value: Any, ttl_s: float) -> None:
        await self.db.run(self.set_sync, key, value, ttl_s)

    def purge_sync(self) -> int:
        with self.db.tx(durable=False) as conn:
            return conn.execute("DELETE FROM cache WHERE expires_at <= ?", (self.clock(),)).rowcount

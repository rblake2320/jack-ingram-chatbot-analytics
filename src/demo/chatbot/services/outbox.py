"""Transactional outbox for CRM delivery.

Rows are inserted in the SAME transaction as the lead/appointment and its ledger entry, so a
crash can never produce a lead without a delivery (or vice versa). Workers in any process
claim due rows with a time-limited lease (``BEGIN IMMEDIATE`` makes the claim exclusive);
a worker that dies mid-delivery simply lets the lease expire and another worker retries.

Delivery is at-least-once. Receivers de-duplicate on the stable ``X-JIM-Delivery-Id`` header
and verify ``X-JIM-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>``.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import random
import sqlite3
import time
import uuid
from typing import Any

import httpx

from ..db import Database
from ..ledger import LedgerEntry, utc_now_iso

log = logging.getLogger(__name__)
ADF_EVENTS = {"lead.created", "appointment.booked"}


def sign(secret: bytes, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret, str(timestamp).encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify_signature(
    secret: bytes, header: str, body: bytes, *, tolerance_s: int = 300, now: float | None = None
) -> bool:
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        supplied = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs((now or time.time()) - timestamp) > tolerance_s:
        return False
    expected = sign(secret, timestamp, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, supplied)


class Outbox:
    def __init__(
        self,
        db: Database,
        http: httpx.AsyncClient,
        *,
        webhook_url: str | None,
        fmt: str,
        signing_key: bytes | None,
        max_attempts: int,
        clock=time.time,
    ) -> None:
        self.db = db
        self.http = http
        self.webhook_url = webhook_url
        self.fmt = fmt
        self.signing_key = signing_key
        self.max_attempts = max_attempts
        self.clock = clock

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    # --- enqueue (inside the caller's transaction) -------------------------------------------
    def enqueue(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        data: dict[str, Any],
        entry: LedgerEntry,
        *,
        adf_xml: str | None = None,
    ) -> str | None:
        if not self.enabled:
            return None
        if self.fmt == "adf" and event_type not in ADF_EVENTS:
            return None
        delivery_id = "dlv_" + uuid.uuid4().hex
        payload = {
            "event": event_type,
            "delivery_id": delivery_id,
            "created_at": utc_now_iso(),
            "data": data,
            "ledger": {"seq": entry.seq, "hash": entry.hash},
        }
        if adf_xml is not None:
            payload["adf_xml"] = adf_xml
        conn.execute(
            "INSERT INTO outbox (id, created_at, event_type, payload, status, attempts, next_attempt_at, ledger_seq)"
            " VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)",
            (delivery_id, payload["created_at"], event_type, json.dumps(payload), self.clock(), entry.seq),
        )
        return delivery_id

    # --- claim / deliver ---------------------------------------------------------------------
    def claim_due_sync(self, *, limit: int = 10, lease_s: float = 60.0) -> list[dict[str, Any]]:
        now = self.clock()
        with self.db.tx() as conn:
            rows = conn.execute(
                "SELECT * FROM outbox WHERE status = 'pending' AND next_attempt_at <= ?"
                " AND (locked_until IS NULL OR locked_until < ?) ORDER BY next_attempt_at LIMIT ?",
                (now, now, limit),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE outbox SET locked_until = ?, attempts = attempts + 1 WHERE id = ?",
                    (now + lease_s, row["id"]),
                )
        return [dict(row) | {"attempts": row["attempts"] + 1} for row in rows]

    def _render(self, row: dict[str, Any]) -> tuple[bytes, str]:
        payload = json.loads(row["payload"])
        if self.fmt == "adf" and payload.get("adf_xml"):
            return payload["adf_xml"].encode("utf-8"), "application/xml"
        payload.pop("adf_xml", None)
        return json.dumps(payload, separators=(",", ":")).encode("utf-8"), "application/json"

    def _finish_sync(self, delivery_id: str, *, ok: bool, attempts: int, error: str | None, permanent: bool) -> str:
        now = self.clock()
        with self.db.tx() as conn:
            if ok:
                conn.execute(
                    "UPDATE outbox SET status = 'delivered', delivered_at = ?, locked_until = NULL, last_error = NULL"
                    " WHERE id = ?",
                    (utc_now_iso(), delivery_id),
                )
                return "delivered"
            if permanent or attempts >= self.max_attempts:
                conn.execute(
                    "UPDATE outbox SET status = 'dead', locked_until = NULL, last_error = ? WHERE id = ?",
                    (error, delivery_id),
                )
                return "dead"
            backoff = min(3600.0, 5.0 * (2 ** (attempts - 1))) * (0.8 + 0.4 * random.random())
            conn.execute(
                "UPDATE outbox SET next_attempt_at = ?, locked_until = NULL, last_error = ? WHERE id = ?",
                (now + backoff, error, delivery_id),
            )
            return "retry"

    async def deliver(self, row: dict[str, Any]) -> str:
        body, content_type = self._render(row)
        timestamp = int(self.clock())
        headers = {
            "content-type": content_type,
            "x-jim-event": row["event_type"],
            "x-jim-delivery-id": row["id"],
            "user-agent": "JackIngramAssistant-Outbox/2.0",
        }
        if self.signing_key:
            headers["x-jim-signature"] = sign(self.signing_key, timestamp, body)
        ok, permanent, error = False, False, None
        try:
            response = await self.http.post(self.webhook_url, content=body, headers=headers, timeout=10.0)
            if 200 <= response.status_code < 300:
                ok = True
            else:
                error = f"HTTP {response.status_code}"
                permanent = 400 <= response.status_code < 500 and response.status_code not in (408, 409, 425, 429)
        except httpx.HTTPError as exc:
            error = type(exc).__name__
        outcome = await self.db.run(
            self._finish_sync, row["id"], ok=ok, attempts=row["attempts"], error=error, permanent=permanent
        )
        if outcome != "delivered":
            log.warning("outbox delivery %s: %s (%s)", row["id"], outcome, error)
        return outcome

    async def process_due(self, *, limit: int = 10) -> dict[str, int]:
        if not self.enabled:
            return {}
        rows = await self.db.run(self.claim_due_sync, limit=limit)
        counts: dict[str, int] = {}
        for row in rows:
            outcome = await self.deliver(row)
            counts[outcome] = counts.get(outcome, 0) + 1
        return counts

    async def run_forever(self, interval_s: float) -> None:
        while True:
            try:
                await self.process_due()
            except asyncio.CancelledError:
                raise
            except Exception:  # fault barrier: the worker must never die
                log.exception("outbox worker iteration failed")
            await asyncio.sleep(interval_s)

    # --- admin -----------------------------------------------------------------------------
    def list_sync(self, status: str | None, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            if status:
                rows = conn.execute(
                    "SELECT id, created_at, event_type, status, attempts, last_error, delivered_at, ledger_seq"
                    " FROM outbox WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, created_at, event_type, status, attempts, last_error, delivered_at, ledger_seq"
                    " FROM outbox ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def requeue_sync(self, delivery_id: str) -> bool:
        with self.db.tx() as conn:
            changed = conn.execute(
                "UPDATE outbox SET status = 'pending', attempts = 0, next_attempt_at = ?, locked_until = NULL"
                " WHERE id = ? AND status = 'dead'",
                (self.clock(), delivery_id),
            ).rowcount
        return changed == 1

    def stats_sync(self) -> dict[str, int]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM outbox GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

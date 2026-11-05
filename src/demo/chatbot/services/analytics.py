"""Analytics events (no raw customer text, ever) and dashboard aggregation."""

from __future__ import annotations

import json
import logging
import statistics
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import Database
from ..ledger import utc_now_iso

log = logging.getLogger(__name__)
_ALLOWED_PROP_TYPES = (str, int, float, bool, type(None))


def _safe_props(props: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in props.items():
        if isinstance(value, _ALLOWED_PROP_TYPES):
            out[key] = value[:120] if isinstance(value, str) else value
        elif isinstance(value, list | tuple):
            out[key] = [v[:60] if isinstance(v, str) else v for v in value[:20] if isinstance(v, _ALLOWED_PROP_TYPES)]
    return out


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


class Analytics:
    def __init__(self, db: Database, *, timezone: str) -> None:
        self.db = db
        self.tz = ZoneInfo(timezone)

    def record_sync(self, event: str, conversation_id: str | None = None, **props: Any) -> None:
        try:
            with self.db.tx(durable=False) as conn:
                conn.execute(
                    "INSERT INTO analytics_events (ts, event, conversation_id, props) VALUES (?, ?, ?, ?)",
                    (utc_now_iso(), event, conversation_id, json.dumps(_safe_props(props))),
                )
        except Exception:  # analytics must never break a customer request
            log.exception("analytics write failed for %s", event)

    async def record(self, event: str, conversation_id: str | None = None, **props: Any) -> None:
        await self.db.run(self.record_sync, event, conversation_id, **props)

    def purge_sync(self, older_than_days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat().replace("+00:00", "Z")
        with self.db.tx(durable=False) as conn:
            return conn.execute("DELETE FROM analytics_events WHERE ts < ?", (cutoff,)).rowcount

    def summary_sync(self, days: int = 30) -> dict[str, Any]:
        started = time.perf_counter()
        days = max(1, min(days, 400))
        since_dt = datetime.now(UTC) - timedelta(days=days)
        since = since_dt.isoformat().replace("+00:00", "Z")
        with self.db.read() as conn:
            events = conn.execute(
                "SELECT ts, event, conversation_id, props FROM analytics_events WHERE ts >= ? ORDER BY ts", (since,)
            ).fetchall()
            leads = conn.execute("SELECT COUNT(*) FROM leads WHERE created_at >= ?", (since,)).fetchone()[0]
            appts = conn.execute(
                "SELECT department, status, COUNT(*) AS n FROM appointments WHERE created_at >= ? GROUP BY department, status",
                (since,),
            ).fetchall()
            handoffs = conn.execute(
                "SELECT created_at, claimed_at, status FROM handoffs WHERE created_at >= ?", (since,)
            ).fetchall()
            feedback = conn.execute(
                "SELECT rating, COUNT(*) AS n FROM feedback WHERE created_at >= ? GROUP BY rating", (since,)
            ).fetchall()
            outbox = conn.execute("SELECT status, COUNT(*) AS n FROM outbox GROUP BY status").fetchall()

        by_event: dict[str, list[tuple[datetime, str | None, dict[str, Any]]]] = defaultdict(list)
        for row in events:
            ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
            by_event[row["event"]].append((ts, row["conversation_id"], json.loads(row["props"])))

        responses = by_event.get("response.sent", [])
        latencies = [p.get("latency_ms") for _, _, p in responses if isinstance(p.get("latency_ms"), int | float)]
        sources = Counter(p.get("source", "unknown") for _, _, p in responses)
        tools = Counter()
        tool_errors = Counter()
        for _, _, p in by_event.get("tool.called", []):
            tools[p.get("name", "?")] += 1
            if not p.get("ok", True):
                tool_errors[p.get("name", "?")] += 1
        topics = Counter(p.get("topic", "other") for _, _, p in by_event.get("message.received", []))
        brands = Counter(b for _, _, p in by_event.get("message.received", []) for b in p.get("brands", []))
        tokens = {
            "input": sum(int(p.get("input_tokens") or 0) for _, _, p in responses),
            "output": sum(int(p.get("output_tokens") or 0) for _, _, p in responses),
            "cache_read": sum(int(p.get("cache_read_tokens") or 0) for _, _, p in responses),
        }

        conversations = {c for _, c, _ in by_event.get("conversation.started", []) if c}
        lead_convs = {c for _, c, _ in by_event.get("lead.created", []) if c}
        appt_convs = {c for _, c, _ in by_event.get("appointment.booked", []) if c}

        daily: dict[str, dict[str, int]] = {}
        for offset in range(days - 1, -1, -1):
            day = (datetime.now(self.tz) - timedelta(days=offset)).date().isoformat()
            daily[day] = {"conversations": 0, "messages": 0, "leads": 0, "appointments": 0}
        for name, key in (("conversation.started", "conversations"), ("message.received", "messages"),
                          ("lead.created", "leads"), ("appointment.booked", "appointments")):  # fmt: skip
            for ts, _, _ in by_event.get(name, []):
                day = ts.astimezone(self.tz).date().isoformat()
                if day in daily:
                    daily[day][key] += 1

        heatmap = [[0] * 24 for _ in range(7)]
        for ts, _, _ in by_event.get("message.received", []):
            local = ts.astimezone(self.tz)
            heatmap[local.weekday()][local.hour] += 1

        waits = []
        for h in handoffs:
            if h["claimed_at"]:
                created = datetime.fromisoformat(h["created_at"].replace("Z", "+00:00"))
                claimed = datetime.fromisoformat(h["claimed_at"].replace("Z", "+00:00"))
                waits.append((claimed - created).total_seconds())
        ratings = {r["rating"]: r["n"] for r in feedback}
        rated = ratings.get(1, 0) + ratings.get(-1, 0)
        n_conv = len(conversations)

        return {
            "window_days": days,
            "generated_at": utc_now_iso(),
            "totals": {
                "conversations": n_conv,
                "messages": len(by_event.get("message.received", [])),
                "responses": len(responses),
                "leads": leads,
                "appointments": sum(r["n"] for r in appts if r["status"] == "booked"),
                "appointments_cancelled": sum(r["n"] for r in appts if r["status"] == "cancelled"),
                "handoffs": len(handoffs),
                "rate_limited": len(by_event.get("rate_limited", [])),
                "errors": len(by_event.get("error", [])),
            },
            "conversion": {
                "lead_rate": round(len(lead_convs) / n_conv, 4) if n_conv else 0.0,
                "appointment_rate": round(len(appt_convs) / n_conv, 4) if n_conv else 0.0,
                "handoff_rate": round(len(handoffs) / n_conv, 4) if n_conv else 0.0,
            },
            "appointments_by_department": {r["department"]: r["n"] for r in appts if r["status"] == "booked"},
            "latency_ms": {
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "p99": _percentile(latencies, 0.99),
                "mean": round(statistics.fmean(latencies), 1) if latencies else None,
            },
            "response_sources": dict(sources),
            "refusals": sum(1 for _, _, p in responses if p.get("refused")),
            "model_fallbacks": sum(1 for _, _, p in responses if p.get("fallback_used")),
            "tokens": tokens,
            "tools": {name: {"calls": n, "errors": tool_errors.get(name, 0)} for name, n in tools.most_common()},
            "topics": dict(topics.most_common()),
            "brand_interest": dict(brands.most_common()),
            "satisfaction": {
                "positive": ratings.get(1, 0),
                "negative": ratings.get(-1, 0),
                "rate": round(ratings.get(1, 0) / rated, 4) if rated else None,
            },
            "handoff_wait_s": {"p50": _percentile(waits, 0.5), "p95": _percentile(waits, 0.95)},
            "daily": [{"date": d, **v} for d, v in daily.items()],
            "heatmap": {"rows": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "values": heatmap},
            "outbox": {r["status"]: r["n"] for r in outbox},
            "compute_ms": round((time.perf_counter() - started) * 1000, 1),
        }

"""Live-agent handoff: queue -> claim -> agent messages -> close (back to the bot)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..db import Database
from ..knowledge import Knowledge
from ..ledger import Ledger, utc_now_iso
from ..text import clean_text
from .common import ServiceError
from .outbox import Outbox


class HandoffService:
    def __init__(self, db: Database, ledger: Ledger, outbox: Outbox, knowledge: Knowledge) -> None:
        self.db = db
        self.ledger = ledger
        self.outbox = outbox
        self.knowledge = knowledge

    def _open(self, conn, conv_id: str):
        return conn.execute(
            "SELECT * FROM handoffs WHERE conversation_id = ? AND status IN ('queued', 'claimed')", (conv_id,)
        ).fetchone()

    def request_sync(self, conv_id: str, reason: str | None) -> dict[str, Any]:
        reason = clean_text(reason or "", max_len=300) or None
        now = self.knowledge.now()
        within_hours = self.knowledge.is_open("sales", now)
        with self.db.tx() as conn:
            existing = self._open(conn, conv_id)
            if existing is not None:
                return self._view(dict(existing), created=False)
            handoff_id = "hnd_" + uuid.uuid4().hex[:20]
            entry = self.ledger.append(
                conn,
                "handoff.requested",
                {"handoff_id": handoff_id, "conversation_id": conv_id, "within_hours": within_hours},
            )
            conn.execute(
                "INSERT INTO handoffs (id, conversation_id, created_at, status, reason, within_hours, ledger_seq)"
                " VALUES (?, ?, ?, 'queued', ?, ?, ?)",
                (handoff_id, conv_id, utc_now_iso(), reason, int(within_hours), entry.seq),
            )
            conn.execute("UPDATE conversations SET status = 'handoff_pending' WHERE id = ?", (conv_id,))
            self.outbox.enqueue(
                conn,
                "handoff.requested",
                {"handoff_id": handoff_id, "conversation_id": conv_id, "reason": reason, "within_hours": within_hours},
                entry,
            )
            row = conn.execute("SELECT * FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
        return self._view(dict(row), created=True)

    def _view(self, row: dict[str, Any], *, created: bool) -> dict[str, Any]:
        view = {
            "handoff_id": row["id"],
            "status": row["status"],
            "within_hours": bool(row["within_hours"]),
            "created": created,
        }
        if not row["within_hours"]:
            nxt = self.knowledge.next_opening("sales", self.knowledge.now())
            view["next_opening"] = nxt.strftime("%A at %I:%M %p").replace(" 0", " ") if nxt else None
        return view

    def status_sync(self, conv_id: str) -> dict[str, Any] | None:
        with self.db.read() as conn:
            row = self._open(conn, conv_id)
        return self._view(dict(row), created=False) if row else None

    # --- agent side (admin-authenticated) --------------------------------------------------
    def list_sync(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM handoffs WHERE status = ? ORDER BY created_at LIMIT ?", (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM handoffs WHERE status != 'closed' ORDER BY created_at LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def get_sync(self, handoff_id: str) -> dict[str, Any]:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
        if row is None:
            raise ServiceError("handoff not found", code="not_found", status=404)
        return dict(row)

    def claim_sync(self, handoff_id: str, agent_name: str) -> dict[str, Any]:
        agent_name = clean_text(agent_name, max_len=60, multiline=False) or "Team member"
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
            if row is None:
                raise ServiceError("handoff not found", code="not_found", status=404)
            if row["status"] == "claimed" and row["agent_name"] != agent_name:
                raise ServiceError(f"already claimed by {row['agent_name']}", code="already_claimed", status=409)
            if row["status"] == "closed":
                raise ServiceError("handoff is closed", code="closed", status=409)
            if row["status"] == "queued":
                self.ledger.append(conn, "handoff.claimed", {"handoff_id": handoff_id, "agent": agent_name})
                conn.execute(
                    "UPDATE handoffs SET status = 'claimed', agent_name = ?, claimed_at = ? WHERE id = ?",
                    (agent_name, utc_now_iso(), handoff_id),
                )
                conn.execute("UPDATE conversations SET status = 'agent' WHERE id = ?", (row["conversation_id"],))
                conn.execute(
                    "INSERT INTO messages (conversation_id, role, content, created_at, meta) VALUES (?, 'system', ?, ?, '{}')",
                    (row["conversation_id"], f"{agent_name} from our team has joined the chat.", utc_now_iso()),
                )
        return self.get_sync(handoff_id)

    def close_sync(self, handoff_id: str) -> dict[str, Any]:
        with self.db.tx() as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
            if row is None:
                raise ServiceError("handoff not found", code="not_found", status=404)
            if row["status"] != "closed":
                self.ledger.append(conn, "handoff.closed", {"handoff_id": handoff_id})
                conn.execute(
                    "UPDATE handoffs SET status = 'closed', closed_at = ? WHERE id = ?", (utc_now_iso(), handoff_id)
                )
                conn.execute("UPDATE conversations SET status = 'bot' WHERE id = ?", (row["conversation_id"],))
                conn.execute(
                    "INSERT INTO messages (conversation_id, role, content, created_at, meta) VALUES (?, 'system', ?, ?, '{}')",
                    (
                        row["conversation_id"],
                        "The team member has left. You're back with the virtual assistant.",
                        utc_now_iso(),
                    ),
                )
        return self.get_sync(handoff_id)

    def agent_message_sync(self, handoff_id: str, content: str) -> int:
        content = clean_text(content, max_len=2000)
        if not content:
            raise ServiceError("message is empty")
        with self.db.tx(durable=False) as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
            if row is None or row["status"] != "claimed":
                raise ServiceError("claim the handoff before replying", code="not_claimed", status=409)
            cursor = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, meta) VALUES (?, 'agent', ?, ?, ?)",
                (row["conversation_id"], content, utc_now_iso(), json.dumps({"agent": row["agent_name"] or ""})),
            )
            return int(cursor.lastrowid)

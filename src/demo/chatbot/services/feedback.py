"""Per-message thumbs up/down with optional comment (re-rating updates; ledger keeps history)."""

from __future__ import annotations

import uuid
from typing import Any

from ..db import Database
from ..ledger import Ledger, utc_now_iso
from ..text import clean_text
from .common import ServiceError


class FeedbackService:
    def __init__(self, db: Database, ledger: Ledger) -> None:
        self.db = db
        self.ledger = ledger

    def submit_sync(self, conv_id: str, message_id: int, rating: int, comment: str | None) -> dict[str, Any]:
        if rating not in (-1, 1):
            raise ServiceError("rating must be 1 or -1")
        comment = clean_text(comment or "", max_len=500) or None
        with self.db.tx() as conn:
            message = conn.execute(
                "SELECT role FROM messages WHERE id = ? AND conversation_id = ?", (message_id, conv_id)
            ).fetchone()
            if message is None or message["role"] not in ("assistant", "agent"):
                raise ServiceError("message not found", code="not_found", status=404)
            existing = conn.execute(
                "SELECT id FROM feedback WHERE conversation_id = ? AND message_id = ?", (conv_id, message_id)
            ).fetchone()
            entry = self.ledger.append(
                conn,
                "feedback.updated" if existing else "feedback.submitted",
                {"conversation_id": conv_id, "message_id": message_id, "rating": rating, "has_comment": bool(comment)},
            )
            now = utc_now_iso()
            if existing:
                conn.execute(
                    "UPDATE feedback SET rating = ?, comment = ?, updated_at = ?, ledger_seq = ? WHERE id = ?",
                    (rating, comment, now, entry.seq, existing["id"]),
                )
                feedback_id = existing["id"]
            else:
                feedback_id = "fb_" + uuid.uuid4().hex[:20]
                conn.execute(
                    "INSERT INTO feedback (id, created_at, updated_at, conversation_id, message_id, rating, comment, ledger_seq)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (feedback_id, now, now, conv_id, message_id, rating, comment, entry.seq),
                )
        return {"feedback_id": feedback_id, "rating": rating, "updated": bool(existing)}

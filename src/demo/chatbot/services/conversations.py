"""Conversation state: display transcript, append-only model history, per-turn lease.

``llm_history`` holds the exact Messages-API blocks (thinking blocks included, unmodified) so
each request's prefix is byte-identical to the previous one: this keeps Claude's preserved
thinking valid and the prompt cache warm. History is only ever appended; when it exceeds the
cap it is cut at a user-turn boundary and thinking blocks are stripped from what remains
(the documented one-time recovery for keep-tail truncation).

A turn lease (``busy_until``) serialises turns per conversation across processes, so a
double-click cannot interleave two model calls on one history.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..db import Database
from ..ledger import utc_now_iso

_THINKING_TYPES = {"thinking", "redacted_thinking"}


def _is_user_text_turn(message: dict[str, Any]) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, str):
        return True
    return bool(content) and all(block.get("type") != "tool_result" for block in content)


def trim_history(history: list[dict[str, Any]], max_messages: int) -> tuple[list[dict[str, Any]], bool]:
    if len(history) <= max_messages:
        return history, False
    start = len(history) - max_messages
    while start < len(history) and not _is_user_text_turn(history[start]):
        start += 1
    kept = history[start:]
    stripped = []
    for message in kept:
        content = message.get("content")
        if isinstance(content, list):
            content = [b for b in content if b.get("type") not in _THINKING_TYPES]
            if not content:
                continue
        stripped.append({**message, "content": content})
    return stripped, True


def strip_thinking(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for message in history:
        content = message.get("content")
        if isinstance(content, list):
            content = [b for b in content if b.get("type") not in _THINKING_TYPES]
            if not content:
                continue
        out.append({**message, "content": content})
    return out


class ConversationStore:
    def __init__(self, db: Database, *, history_max_messages: int, clock=time.time) -> None:
        self.db = db
        self.history_max_messages = history_max_messages
        self.clock = clock

    def create_sync(self, conv_id: str, user_agent: str | None) -> None:
        now = utc_now_iso()
        with self.db.tx(durable=False) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO conversations (id, created_at, updated_at, user_agent) VALUES (?, ?, ?, ?)",
                (conv_id, now, now, (user_agent or "")[:200]),
            )

    def get_sync(self, conv_id: str) -> dict[str, Any] | None:
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT id, created_at, updated_at, status, turn_count FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
        return dict(row) if row else None

    def acquire_turn_sync(self, conv_id: str, lease_s: float) -> bool:
        now = self.clock()
        with self.db.tx(durable=False) as conn:
            changed = conn.execute(
                "UPDATE conversations SET busy_until = ? WHERE id = ? AND (busy_until IS NULL OR busy_until < ?)",
                (now + lease_s, conv_id, now),
            ).rowcount
        return changed == 1

    def release_turn_sync(self, conv_id: str) -> None:
        with self.db.tx(durable=False) as conn:
            conn.execute("UPDATE conversations SET busy_until = NULL WHERE id = ?", (conv_id,))

    def history_sync(self, conv_id: str) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            row = conn.execute("SELECT llm_history FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        return json.loads(row["llm_history"]) if row else []

    def append_history_sync(
        self, conv_id: str, new_messages: list[dict[str, Any]], *, replace: list | None = None
    ) -> bool:
        """Append (or, for a one-time recovery, replace) model history. Returns True if trimmed."""
        with self.db.tx(durable=False) as conn:
            row = conn.execute("SELECT llm_history FROM conversations WHERE id = ?", (conv_id,)).fetchone()
            if row is None:
                return False
            history = replace if replace is not None else json.loads(row["llm_history"])
            history = [*history, *new_messages]
            history, trimmed = trim_history(history, self.history_max_messages)
            conn.execute(
                "UPDATE conversations SET llm_history = ?, updated_at = ?, turn_count = turn_count + 1 WHERE id = ?",
                (json.dumps(history, ensure_ascii=False), utc_now_iso(), conv_id),
            )
        return trimmed

    def add_message_sync(self, conv_id: str, role: str, content: str, meta: dict[str, Any] | None = None) -> int:
        with self.db.tx(durable=False) as conn:
            cursor = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, meta) VALUES (?, ?, ?, ?, ?)",
                (conv_id, role, content, utc_now_iso(), json.dumps(meta or {})),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (utc_now_iso(), conv_id))
            return int(cursor.lastrowid)

    def messages_after_sync(self, conv_id: str, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT id, role, content, created_at, meta FROM messages WHERE conversation_id = ? AND id > ?"
                " ORDER BY id LIMIT ?",
                (conv_id, after_id, limit),
            ).fetchall()
        return [dict(r) | {"meta": json.loads(r["meta"])} for r in rows]

    def message_sync(self, conv_id: str, message_id: int) -> dict[str, Any] | None:
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT id, role FROM messages WHERE conversation_id = ? AND id = ?", (conv_id, message_id)
            ).fetchone()
        return dict(row) if row else None

    def user_texts_sync(self, conv_id: str) -> list[str]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' ORDER BY id", (conv_id,)
            ).fetchall()
        return [r["content"] for r in rows]

    def set_status_sync(self, conv_id: str, status: str) -> None:
        with self.db.tx(durable=False) as conn:
            conn.execute(
                "UPDATE conversations SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now_iso(), conv_id)
            )

    def purge_sync(self, older_than_days: int) -> int:
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.clock() - older_than_days * 86400))
        with self.db.tx(durable=False) as conn:
            return conn.execute(
                "DELETE FROM conversations WHERE updated_at < ? AND status = 'bot'"
                " AND id NOT IN (SELECT conversation_id FROM handoffs WHERE status != 'closed')",
                (cutoff,),
            ).rowcount

"""Tamper-evident, append-only ledger (hash chain + HMAC seal).

Every business event (lead, appointment, handoff, feedback, service-record import) appends
one entry *inside the same SQLite transaction* as the business row and its outbox message,
so the three commit or roll back together.

Entry integrity:
    hash = SHA-256(canonical_json({seq, ts, kind, idempotency_key, request_fp, payload, prev_hash}))
    mac  = HMAC-SHA-256(LEDGER_HMAC_KEY, hash)

* Editing any field, reordering, or deleting a middle entry breaks the chain.
* Recomputing the chain after an edit requires the HMAC key, so a database-only attacker
  cannot re-seal forged entries.
* Truncating the *tail* is only detectable against an external anchor: every outbox
  delivery carries the entry's ``seq``/``hash`` and ``/api/admin/ledger/head`` exposes the
  head for witnesses. ``python -m chatbot.cli export-ledger`` writes a sealed bundle.

PII is never written to the ledger. Payloads carry an HMAC *digest* of the full business
record instead, so rows can be verified against the ledger yet still be erased on request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

GENESIS_HASH = "0" * 64


class IdempotencyConflict(Exception):
    """The idempotency key was already used with a different request."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class LedgerEntry:
    seq: int
    ts: str
    kind: str
    idempotency_key: str | None
    request_fp: str | None
    payload: dict[str, Any]
    prev_hash: str
    hash: str
    mac: str
    replayed: bool = False


@dataclass
class VerifyReport:
    ok: bool
    entries: int
    head_seq: int
    head_hash: str
    failures: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "entries": self.entries,
            "head_seq": self.head_seq,
            "head_hash": self.head_hash,
            "failures": self.failures,
        }


def _row_to_entry(row: sqlite3.Row, *, replayed: bool = False) -> LedgerEntry:
    return LedgerEntry(
        seq=row["seq"],
        ts=row["ts"],
        kind=row["kind"],
        idempotency_key=row["idempotency_key"],
        request_fp=row["request_fp"],
        payload=json.loads(row["payload"]),
        prev_hash=row["prev_hash"],
        hash=row["hash"],
        mac=row["mac"],
        replayed=replayed,
    )


class Ledger:
    def __init__(self, key: bytes) -> None:
        if len(key) < 16:
            raise ValueError("ledger HMAC key too short")
        self._key = key

    # --- crypto helpers ------------------------------------------------------------------
    def _hash(self, body: dict[str, Any]) -> str:
        return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()

    def _mac(self, entry_hash: str) -> str:
        return hmac.new(self._key, entry_hash.encode("ascii"), hashlib.sha256).hexdigest()

    def record_digest(self, record: dict[str, Any]) -> str:
        """Keyed digest of a business record (lets rows be verified without storing PII here)."""
        return hmac.new(self._key, canonical_json(record).encode("utf-8"), hashlib.sha256).hexdigest()

    # --- reads ---------------------------------------------------------------------------
    def find_idempotent(
        self, conn: sqlite3.Connection, idempotency_key: str | None, request_fp: str | None
    ) -> LedgerEntry | None:
        """Return the prior entry for this key, or raise if the key was reused differently."""
        if not idempotency_key:
            return None
        row = conn.execute("SELECT * FROM ledger WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if row is None:
            return None
        if request_fp is not None and row["request_fp"] != request_fp:
            raise IdempotencyConflict(idempotency_key)
        return _row_to_entry(row, replayed=True)

    def head(self, conn: sqlite3.Connection) -> tuple[int, str]:
        row = conn.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        return (row["seq"], row["hash"]) if row else (0, GENESIS_HASH)

    # --- writes --------------------------------------------------------------------------
    def append(
        self,
        conn: sqlite3.Connection,
        kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        request_fp: str | None = None,
    ) -> LedgerEntry:
        """Append one entry. MUST run inside a ``Database.tx()`` (BEGIN IMMEDIATE) block."""
        if not conn.in_transaction:
            raise RuntimeError("ledger.append requires an open write transaction")
        prior = self.find_idempotent(conn, idempotency_key, request_fp)
        if prior is not None:
            return prior
        last_seq, prev_hash = self.head(conn)
        seq = last_seq + 1
        ts = utc_now_iso()
        body = {
            "seq": seq,
            "ts": ts,
            "kind": kind,
            "idempotency_key": idempotency_key,
            "request_fp": request_fp,
            "payload": payload,
            "prev_hash": prev_hash,
        }
        entry_hash = self._hash(body)
        mac = self._mac(entry_hash)
        conn.execute(
            "INSERT INTO ledger (seq, ts, kind, idempotency_key, request_fp, payload, prev_hash, hash, mac)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (seq, ts, kind, idempotency_key, request_fp, canonical_json(payload), prev_hash, entry_hash, mac),
        )
        return LedgerEntry(seq, ts, kind, idempotency_key, request_fp, payload, prev_hash, entry_hash, mac)

    # --- verification ----------------------------------------------------------------------
    def verify(self, conn: sqlite3.Connection, *, max_failures: int = 25) -> VerifyReport:
        expected_seq = 1
        prev_hash = GENESIS_HASH
        count = 0
        failures: list[dict[str, Any]] = []
        cursor = conn.execute("SELECT * FROM ledger ORDER BY seq ASC")
        for row in cursor:
            count += 1
            seq = row["seq"]
            problems: list[str] = []
            if seq != expected_seq:
                problems.append(f"sequence gap: expected {expected_seq}, found {seq}")
            if row["prev_hash"] != prev_hash:
                problems.append("prev_hash does not match previous entry")
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                payload = None
                problems.append("payload is not valid JSON")
            body = {
                "seq": seq,
                "ts": row["ts"],
                "kind": row["kind"],
                "idempotency_key": row["idempotency_key"],
                "request_fp": row["request_fp"],
                "payload": payload,
                "prev_hash": row["prev_hash"],
            }
            recomputed = self._hash(body)
            if recomputed != row["hash"]:
                problems.append("hash mismatch (entry content altered)")
            if not hmac.compare_digest(self._mac(row["hash"]), row["mac"]):
                problems.append("HMAC seal invalid (forged or re-sealed without the key)")
            if problems and len(failures) < max_failures:
                failures.append({"seq": seq, "problems": problems})
            prev_hash = row["hash"]
            expected_seq = seq + 1
        head_seq = expected_seq - 1
        return VerifyReport(ok=not failures, entries=count, head_seq=head_seq, head_hash=prev_hash, failures=failures)

    def export_bundle(self, conn: sqlite3.Connection) -> bytes:
        """Sealed JSONL export: one line per entry, then a seal line over the whole body."""
        lines = [
            canonical_json(
                {
                    "seq": r["seq"],
                    "ts": r["ts"],
                    "kind": r["kind"],
                    "idempotency_key": r["idempotency_key"],
                    "request_fp": r["request_fp"],
                    "payload": json.loads(r["payload"]),
                    "prev_hash": r["prev_hash"],
                    "hash": r["hash"],
                    "mac": r["mac"],
                }
            )
            for r in conn.execute("SELECT * FROM ledger ORDER BY seq ASC")
        ]
        body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        body_sha = hashlib.sha256(body).hexdigest()
        head_seq, head_hash = self.head(conn)
        seal = {
            "type": "seal",
            "exported_at": utc_now_iso(),
            "entries": len(lines),
            "head_seq": head_seq,
            "head_hash": head_hash,
            "body_sha256": body_sha,
            "mac": hmac.new(self._key, body_sha.encode("ascii"), hashlib.sha256).hexdigest(),
        }
        return body + canonical_json(seal).encode("utf-8") + b"\n"

    def verify_bundle(self, data: bytes) -> bool:
        body, _, seal_line = data.rstrip(b"\n").rpartition(b"\n")
        if not seal_line:
            return False
        body = body + b"\n" if body else b""
        try:
            seal = json.loads(seal_line)
        except ValueError:
            return False
        body_sha = hashlib.sha256(body).hexdigest()
        expected = hmac.new(self._key, body_sha.encode("ascii"), hashlib.sha256).hexdigest()
        return seal.get("body_sha256") == body_sha and hmac.compare_digest(expected, str(seal.get("mac", "")))

"""SQLite persistence (WAL mode).

Concurrency model: every write runs inside ``BEGIN IMMEDIATE``, which takes SQLite's
database-level write lock. That serialises writers across *processes* (multiple uvicorn
workers, the CLI, tests that spawn processes) on Windows and Linux alike, so read-check-write
sequences such as "count bookings for this slot, then insert" are race-free without any
extra locking. Readers never block writers in WAL mode.

Durability: ``durable=True`` transactions run with ``synchronous=FULL`` (fsync on commit);
high-volume, loss-tolerant data (rate-limit counters, cache, analytics) uses ``NORMAL``.

Note: WAL needs a local filesystem. Do not put the database on NFS/SMB shares.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger (
    seq             INTEGER PRIMARY KEY,
    ts              TEXT NOT NULL,
    kind            TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    request_fp      TEXT,
    payload         TEXT NOT NULL,
    prev_hash       TEXT NOT NULL,
    hash            TEXT NOT NULL,
    mac             TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;

CREATE TABLE IF NOT EXISTS conversations (
    id           TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'bot' CHECK (status IN ('bot', 'handoff_pending', 'agent')),
    turn_count   INTEGER NOT NULL DEFAULT 0,
    busy_until   REAL,
    llm_history  TEXT NOT NULL DEFAULT '[]',
    user_agent   TEXT,
    meta         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'agent', 'system')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    meta            TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS leads (
    id                TEXT PRIMARY KEY,
    created_at        TEXT NOT NULL,
    source            TEXT NOT NULL,
    conversation_id   TEXT,
    first_name        TEXT NOT NULL,
    last_name         TEXT,
    email             TEXT,
    phone             TEXT,
    interest          TEXT NOT NULL,
    vehicle           TEXT NOT NULL DEFAULT '{}',
    comments          TEXT,
    preferred_contact TEXT,
    consent           INTEGER NOT NULL CHECK (consent = 1),
    status            TEXT NOT NULL DEFAULT 'new',
    ledger_seq        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at);

CREATE TABLE IF NOT EXISTS appointments (
    id                TEXT PRIMARY KEY,
    confirmation_code TEXT NOT NULL UNIQUE,
    created_at        TEXT NOT NULL,
    department        TEXT NOT NULL,
    slot_start        TEXT NOT NULL,
    slot_end          TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled')),
    first_name        TEXT NOT NULL,
    last_name         TEXT NOT NULL,
    phone             TEXT NOT NULL,
    email             TEXT,
    vehicle           TEXT NOT NULL DEFAULT '{}',
    service_type      TEXT,
    notes             TEXT,
    conversation_id   TEXT,
    source            TEXT NOT NULL,
    ledger_seq        INTEGER NOT NULL,
    cancelled_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_appointments_slot ON appointments(department, slot_start, status);
CREATE INDEX IF NOT EXISTS idx_appointments_phone ON appointments(phone, status);

CREATE TABLE IF NOT EXISTS handoffs (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('queued', 'claimed', 'closed')),
    reason          TEXT,
    within_hours    INTEGER NOT NULL,
    agent_name      TEXT,
    claimed_at      TEXT,
    closed_at       TEXT,
    ledger_seq      INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_handoffs_one_open
    ON handoffs(conversation_id) WHERE status IN ('queued', 'claimed');

CREATE TABLE IF NOT EXISTS feedback (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    message_id      INTEGER NOT NULL,
    rating          INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    comment         TEXT,
    ledger_seq      INTEGER NOT NULL,
    UNIQUE (conversation_id, message_id)
);

CREATE TABLE IF NOT EXISTS service_records (
    id                 TEXT PRIMARY KEY,
    vin                TEXT NOT NULL,
    customer_last_name TEXT NOT NULL,
    service_date       TEXT NOT NULL,
    mileage            INTEGER,
    description        TEXT NOT NULL,
    ro_number          TEXT,
    source             TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    ledger_seq         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_service_records_vin ON service_records(vin);

CREATE TABLE IF NOT EXISTS outbox (
    id              TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'dead')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    locked_until    REAL,
    last_error      TEXT,
    delivered_at    TEXT,
    ledger_seq      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_outbox_due ON outbox(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS analytics_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    event           TEXT NOT NULL,
    conversation_id TEXT,
    props           TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_event_ts ON analytics_events(event, ts);
CREATE INDEX IF NOT EXISTS idx_events_ts ON analytics_events(ts);

CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_limits (
    bucket       TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    count        INTEGER NOT NULL,
    PRIMARY KEY (bucket, window_start)
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self, *, durable: bool = True) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(f"PRAGMA synchronous={'FULL' if durable else 'NORMAL'}")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise RuntimeError(f"SQLite refused WAL mode (got {mode!r}); use a local filesystem")
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        finally:
            conn.close()

    @contextmanager
    def tx(self, *, durable: bool = True) -> Iterator[sqlite3.Connection]:
        """Serialised write transaction (cross-process safe)."""
        conn = self._connect(durable=durable)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect(durable=False)
        try:
            yield conn
        finally:
            conn.close()

    async def run(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        """Run blocking DB work off the event loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    def ping(self) -> bool:
        with self.tx(durable=False) as conn:
            conn.execute("SELECT 1").fetchone()
        return True

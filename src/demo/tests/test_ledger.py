"""Ledger: chain integrity, forgery/tamper detection, idempotency, crash rollback, multi-process appends."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import sqlite3

import pytest

from chatbot.db import Database
from chatbot.ledger import IdempotencyConflict, Ledger, canonical_json

from . import mp_workers

KEY = b"k" * 32


@pytest.fixture
def ledger_db(tmp_path):
    db = Database(tmp_path / "ledger.sqlite3")
    db.initialize()
    return db, Ledger(KEY)


def _append(db, ledger, n=3):
    entries = []
    for i in range(n):
        with db.tx() as conn:
            entries.append(ledger.append(conn, "evt", {"i": i}))
    return entries


def _verify(db, ledger):
    with db.read() as conn:
        return ledger.verify(conn)


def _unlock(conn):
    conn.execute("DROP TRIGGER ledger_no_update")
    conn.execute("DROP TRIGGER ledger_no_delete")


def test_chain_verifies_and_links(ledger_db):
    db, ledger = ledger_db
    entries = _append(db, ledger, 5)
    report = _verify(db, ledger)
    assert report.ok and report.entries == 5 and report.head_seq == 5
    assert entries[0].prev_hash == "0" * 64
    assert all(entries[i].prev_hash == entries[i - 1].hash for i in range(1, 5))
    assert report.head_hash == entries[-1].hash


def test_empty_ledger_verifies(ledger_db):
    db, ledger = ledger_db
    report = _verify(db, ledger)
    assert report.ok and report.entries == 0 and report.head_seq == 0


def test_triggers_block_update_and_delete(ledger_db):
    db, ledger = ledger_db
    _append(db, ledger, 1)
    with db.read() as conn:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE ledger SET payload = '{}' WHERE seq = 1")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM ledger WHERE seq = 1")


def test_payload_edit_detected(ledger_db):
    db, ledger = ledger_db
    _append(db, ledger, 3)
    with db.tx() as conn:
        _unlock(conn)
        conn.execute("UPDATE ledger SET payload = ? WHERE seq = 2", (canonical_json({"i": 999}),))
    report = _verify(db, ledger)
    assert not report.ok
    assert report.failures[0]["seq"] == 2
    assert any("hash mismatch" in p for p in report.failures[0]["problems"])


def test_reseal_without_key_detected(ledger_db):
    """Attacker edits a payload and recomputes the SHA-256 (no HMAC key): the seal fails."""
    db, ledger = ledger_db
    _append(db, ledger, 3)
    with db.tx() as conn:
        _unlock(conn)
        row = conn.execute("SELECT * FROM ledger WHERE seq = 2").fetchone()
        body = {"seq": 2, "ts": row["ts"], "kind": row["kind"], "idempotency_key": None, "request_fp": None,
                "payload": {"i": 999}, "prev_hash": row["prev_hash"]}  # fmt: skip
        forged = hashlib.sha256(canonical_json(body).encode()).hexdigest()
        conn.execute("UPDATE ledger SET payload = ?, hash = ? WHERE seq = 2", (canonical_json({"i": 999}), forged))
    report = _verify(db, ledger)
    problems = {f["seq"]: f["problems"] for f in report.failures}
    assert any("HMAC seal invalid" in p for p in problems[2])
    assert any("prev_hash" in p for p in problems[3])  # chain to the next entry breaks too


def test_middle_deletion_detected(ledger_db):
    db, ledger = ledger_db
    _append(db, ledger, 4)
    with db.tx() as conn:
        _unlock(conn)
        conn.execute("DELETE FROM ledger WHERE seq = 2")
    report = _verify(db, ledger)
    assert not report.ok
    assert any("sequence gap" in p for f in report.failures for p in f["problems"])


def test_swapped_entries_detected(ledger_db):
    db, ledger = ledger_db
    _append(db, ledger, 3)
    with db.tx() as conn:
        _unlock(conn)
        a = conn.execute("SELECT payload FROM ledger WHERE seq = 1").fetchone()[0]
        b = conn.execute("SELECT payload FROM ledger WHERE seq = 2").fetchone()[0]
        conn.execute("UPDATE ledger SET payload = ? WHERE seq = 1", (b,))
        conn.execute("UPDATE ledger SET payload = ? WHERE seq = 2", (a,))
    assert not _verify(db, ledger).ok


def test_wrong_key_rejects_every_seal(ledger_db):
    db, _ = ledger_db
    _append(db, Ledger(KEY), 2)
    report = _verify(db, Ledger(b"x" * 32))
    assert not report.ok and len(report.failures) == 2


def test_tail_truncation_visible_against_external_anchor(ledger_db):
    """Chain-only verification cannot see tail truncation; the exported head (anchor) can."""
    db, ledger = ledger_db
    _append(db, ledger, 3)
    anchor = _verify(db, ledger).head_hash
    with db.tx() as conn:
        _unlock(conn)
        conn.execute("DELETE FROM ledger WHERE seq = 3")
    report = _verify(db, ledger)
    assert report.ok  # documented limitation
    assert report.head_hash != anchor  # ...which the external anchor exposes


def test_idempotent_replay_returns_original(ledger_db):
    db, ledger = ledger_db
    with db.tx() as conn:
        first = ledger.append(conn, "evt", {"a": 1}, idempotency_key="k1", request_fp="fp1")
    with db.tx() as conn:
        again = ledger.append(conn, "evt", {"a": 2}, idempotency_key="k1", request_fp="fp1")
    assert again.replayed and again.seq == first.seq and again.payload == {"a": 1}
    assert _verify(db, ledger).entries == 1


def test_idempotency_key_reuse_with_different_request_conflicts(ledger_db):
    db, ledger = ledger_db
    with db.tx() as conn:
        ledger.append(conn, "evt", {"a": 1}, idempotency_key="k1", request_fp="fp1")
    with pytest.raises(IdempotencyConflict), db.tx() as conn:
        ledger.append(conn, "evt", {"a": 1}, idempotency_key="k1", request_fp="fp-other")


def test_append_outside_transaction_refused(ledger_db):
    db, ledger = ledger_db
    with db.read() as conn, pytest.raises(RuntimeError):
        ledger.append(conn, "evt", {})


def test_crash_inside_transaction_rolls_back(ledger_db):
    db, ledger = ledger_db
    _append(db, ledger, 1)
    with pytest.raises(RuntimeError), db.tx() as conn:
        ledger.append(conn, "evt", {"doomed": True})
        raise RuntimeError("simulated crash before commit")
    report = _verify(db, ledger)
    assert report.ok and report.entries == 1
    _append(db, ledger, 1)  # the chain continues cleanly after the rollback
    assert _verify(db, ledger).ok


def test_canonical_json_is_key_order_independent():
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == canonical_json({"a": [1, {"c": 3, "d": 2}], "b": 1})


@pytest.mark.slow
def test_concurrent_multiprocess_appends_keep_chain_valid(tmp_path):
    db = Database(tmp_path / "race.sqlite3")
    db.initialize()
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(4) as pool:
        results = pool.starmap(mp_workers.append_entries, [(str(db.path), KEY, w, 40) for w in range(4)])
    assert sum(results) == 160
    with db.read() as conn:
        report = Ledger(KEY).verify(conn)
        seqs = [r[0] for r in conn.execute("SELECT seq FROM ledger ORDER BY seq")]
    assert report.ok and report.entries == 160
    assert seqs == list(range(1, 161))


def test_export_bundle_seal(ledger_db):
    db, ledger = ledger_db
    _append(db, ledger, 3)
    with db.read() as conn:
        bundle = ledger.export_bundle(conn)
    assert ledger.verify_bundle(bundle)
    lines = bundle.decode().splitlines()
    assert json.loads(lines[-1])["entries"] == 3
    tampered = bundle.replace(b'"i":1', b'"i":7')
    assert not ledger.verify_bundle(tampered)
    truncated = ("\n".join(lines[:1] + lines[2:]) + "\n").encode()
    assert not ledger.verify_bundle(truncated)
    assert not Ledger(b"z" * 32).verify_bundle(bundle)
    assert not ledger.verify_bundle(b"not a bundle")

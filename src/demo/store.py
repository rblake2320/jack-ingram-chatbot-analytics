"""SQLite transactions protect session state, resets, limits and aggregate receipts."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class ConversationChanged(Exception):
    pass


class SessionExpired(Exception):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations(
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    updated REAL NOT NULL, history TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, visitor TEXT NOT NULL,
                    intent TEXT NOT NULL, brand TEXT NOT NULL, source TEXT NOT NULL,
                    outcome TEXT NOT NULL, latency_ms REAL NOT NULL,
                    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS events_at ON events(at);
                CREATE TABLE IF NOT EXISTS limits(
                    key TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def prune(self, db):
        now = time.time()
        db.execute("DELETE FROM conversations WHERE updated < ?", (now - 3600,))
        db.execute("DELETE FROM events WHERE at < ?", (now - 90 * 86400,))
        db.execute("DELETE FROM limits WHERE started < ?", (now - 60,))

    def active(self, conversation):
        with self.connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM conversations WHERE id=? AND updated>=?",
                    (conversation, time.time() - 3600),
                ).fetchone()
                is not None
            )

    def history(self, conversation, require_existing=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.prune(db)
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation,)).fetchone()
            if row is None:
                if require_existing:
                    raise SessionExpired()
                db.execute("INSERT INTO conversations VALUES(?,0,?,'[]')", (conversation, time.time()))
                return 0, []
            db.execute("UPDATE conversations SET updated=? WHERE id=?", (time.time(), conversation))
            return row["revision"], json.loads(row["history"])

    def finish(self, conversation, revision, history, event=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE conversations SET revision=revision+1,updated=?,history=? WHERE id=? AND revision=?",
                (time.time(), json.dumps(history[-20:]), conversation, revision),
            ).rowcount
            if changed != 1:
                raise ConversationChanged()
            if event:
                self._event(db, event)

    def event(self, event, conversation, revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.prune(db)
            row = db.execute("SELECT revision FROM conversations WHERE id=?", (conversation,)).fetchone()
            if row and row["revision"] == revision:
                self._event(db, event)

    @staticmethod
    def _event(db, event):
        db.execute(
            "INSERT INTO events(at,visitor,intent,brand,source,outcome,latency_ms,"
            "input_tokens,output_tokens) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                time.time(),
                event["visitor"],
                event["intent"],
                event["brand"],
                event["source"],
                event["outcome"],
                event["latency_ms"],
                event["input_tokens"],
                event["output_tokens"],
            ),
        )

    def reset(self, conversation, visitor=None):
        with self.connect() as db:
            db.execute("DELETE FROM conversations WHERE id=?", (conversation,))
            if visitor:
                db.execute("DELETE FROM events WHERE visitor=?", (visitor,))

    def allow(self, key, maximum):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.prune(db)
            row = db.execute("SELECT count FROM limits WHERE key=?", (key,)).fetchone()
            if row and row["count"] >= maximum:
                return False
            db.execute(
                "INSERT INTO limits VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET count=count+1",
                (key, time.time()),
            )
            return True

    def summary(self, days=None):
        since = time.time() - days * 86400 if days else 0
        with self.connect() as db:
            self.prune(db)
            totals = dict(
                db.execute(
                    """
                SELECT COUNT(*) AS messages, COUNT(DISTINCT visitor) AS visitors,
                SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS successes,
                SUM(CASE WHEN outcome='error' THEN 1 ELSE 0 END) AS errors,
                COALESCE(SUM(input_tokens),0) AS input_tokens,
                COALESCE(SUM(output_tokens),0) AS output_tokens,
                COALESCE(AVG(latency_ms),0) AS average_latency_ms,
                MIN(at) AS coverage_start, MAX(at) AS coverage_end
                FROM events WHERE at>=?
            """,
                    (since,),
                ).fetchone()
            )
            for column in ("intent", "brand", "source"):
                totals[column + "s"] = [
                    dict(row)
                    for row in db.execute(
                        f"SELECT {column} AS label,COUNT(*) AS count FROM events WHERE at>=? "
                        f"GROUP BY {column} ORDER BY count DESC,label",
                        (since,),
                    )
                ]
        return totals

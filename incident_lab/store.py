"""Durable evidence, checkpoints, approvals, executions, and an ordered audit trail."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


class Store:
    def __init__(self, path=":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Use autocommit for individual writes; transaction() explicitly groups the
        # approval checks and simulated deployment mutation that must be atomic.
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.execute("PRAGMA busy_timeout = 5000")
        # Objects keep JSON records keyed by kind + ID. Events form a separate,
        # ordered trace; they are durable, but not protected from direct DB editing.
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS objects (
                kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY (kind, id)
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                event TEXT NOT NULL, body TEXT NOT NULL
            );
        """)

    def put(self, kind, key, value):
        # Upsert makes checkpoints replaceable. Higher-level runtime handlers enforce
        # stronger rules, such as refusing different proposals under the same action ID.
        self.db.execute(
            "INSERT INTO objects VALUES (?, ?, ?) "
            "ON CONFLICT(kind, id) DO UPDATE SET body=excluded.body",
            (kind, key, json.dumps(value, sort_keys=True)),
        )

    def get(self, kind, key):
        # Bound SQL parameters treat IDs as values rather than executable SQL text.
        row = self.db.execute(
            "SELECT body FROM objects WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        if row is None:
            raise KeyError(f"Missing {kind}: {key}")
        return json.loads(row[0])

    def all(self, kind):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT body FROM objects WHERE kind=? ORDER BY id", (kind,)
        )]

    def has(self, kind, key):
        return self.db.execute(
            "SELECT 1 FROM objects WHERE kind=? AND id=?", (kind, key)
        ).fetchone() is not None

    def event(self, name, **body):
        self.db.execute(
            "INSERT INTO events(event, body) VALUES (?, ?)",
            (name, json.dumps(body, sort_keys=True)),
        )

    def events(self):
        # Sequence, rather than timestamp alone, preserves order for near-simultaneous events.
        return [dict(sequence=row[0], at=row[1], event=row[2], **json.loads(row[3]))
                for row in self.db.execute(
                    "SELECT sequence, at, event, body FROM events ORDER BY sequence"
                )]

    @contextmanager
    def transaction(self):
        """Serialize approval checks and simulated writes, including idempotency checks."""
        # Take the write reservation before reading the execution record so concurrent
        # callers cannot both see "not executed" and apply the same simulated action.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            # Include interruptions as well as ordinary errors in rollback handling.
            self.db.rollback()
            raise
        else:
            # A successful caller publishes all grouped writes at this point.
            self.db.commit()

    def close(self):
        self.db.close()

"""Durable evidence, checkpoints, approvals, executions, and an ordered audit trail."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


class Store:
    def __init__(self, path=":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.execute("PRAGMA busy_timeout = 5000")
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
        self.db.execute(
            "INSERT INTO objects VALUES (?, ?, ?) "
            "ON CONFLICT(kind, id) DO UPDATE SET body=excluded.body",
            (kind, key, json.dumps(value, sort_keys=True)),
        )

    def get(self, kind, key):
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
        return [dict(sequence=row[0], at=row[1], event=row[2], **json.loads(row[3]))
                for row in self.db.execute(
                    "SELECT sequence, at, event, body FROM events ORDER BY sequence"
                )]

    @contextmanager
    def transaction(self):
        """Serialize approval checks and simulated writes, including idempotency checks."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def close(self):
        self.db.close()

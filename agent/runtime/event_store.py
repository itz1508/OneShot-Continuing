"""Append-only event store — no history erasure."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any


class EventStore:
    """Append-only event store for workflow observability."""

    def __init__(self, state_root: str | Path) -> None:
        self.state_root = Path(state_root)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_root / "events.db"
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
            if "event_id" not in columns:
                conn.execute("ALTER TABLE events ADD COLUMN event_id TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_events_identity ON events(event_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id)")
            conn.commit()
        finally:
            conn.close()

    def append(self, task_id: str, event_type: str, event_data: str, *, event_id: str | None = None) -> int:
        """Append a lifecycle event; keyed retries return the original sequence."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("BEGIN IMMEDIATE")
            if event_id is not None:
                if not event_id:
                    raise ValueError("event_id must not be empty")
                existing = conn.execute(
                    "SELECT seq, task_id, event_type, event_data FROM events WHERE event_id = ?", (event_id,)
                ).fetchone()
                if existing is not None:
                    if existing[1:] != (task_id, event_type, event_data):
                        raise ValueError(f"conflicting lifecycle event: {event_id}")
                    conn.execute("COMMIT")
                    return int(existing[0])
            cursor = conn.execute(
                "INSERT INTO events (event_id, task_id, event_type, event_data) VALUES (?, ?, ?, ?)",
                (event_id, task_id, event_type, event_data),
            )
            conn.execute("COMMIT")
            return cursor.lastrowid or 0
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def list(self, task_id: str) -> list[dict[str, Any]]:
        """List events for a task, ordered by sequence."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                "SELECT seq, event_type, event_data, created_at, event_id FROM events WHERE task_id = ? ORDER BY seq",
                (task_id,),
            ).fetchall()
            return [
                {"seq": r[0], "event_type": r[1], "event_data": r[2], "created_at": r[3], "event_id": r[4]}
                for r in rows
            ]
        finally:
            conn.close()


class AppendOnlyEventStore:
    """In-memory append-only event store with hash-chained events."""

    def __init__(self) -> None:
        self._events: list[str] = []
        self._digests: list[str] = []

    def append(self, event: object) -> str:
        """Append an ExecutionEvent. Returns its digest. Rejects stale chains."""
        from agent.contracts.observability import ExecutionEvent

        if not isinstance(event, ExecutionEvent):
            raise TypeError(f"Expected ExecutionEvent, got {type(event).__name__}")
        # Verify hash chain
        if self._digests:
            expected = self._digests[-1]
            if event.previous_event_digest is not None and event.previous_event_digest != expected:
                raise ValueError(f"Hash chain broken: expected {expected}, got {event.previous_event_digest}")
        payload = event.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        self._events.append(payload)
        self._digests.append(digest)
        return digest

    @property
    def events(self) -> list[str]:
        return list(self._events)

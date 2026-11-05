"""SQLite durable checkpoint store with compare-and-swap revisions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import ClassVar

from agent.contracts.host import Checkpoint
from agent.runtime.canonical_serialization import canonical_bytes
from agent.runtime.checkpoint_store import CheckpointStoreError, SchemaCompatibilityError


class StaleCheckpointError(CheckpointStoreError):
    """Raised when a checkpoint write conflicts with an existing revision."""


class SQLiteCheckpointStore:
    """SQLite-backed checkpoint store with CAS semantics."""

    _EXPECTED_COLUMNS: ClassVar[set[str]] = {"checkpoint_id", "revision", "payload"}

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(str(path))
        # Check if table exists with incompatible schema
        existing = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        ).fetchone()
        if existing is not None:
            cols = {row[1] for row in self.connection.execute("PRAGMA table_info(checkpoints)")}
            if not self._EXPECTED_COLUMNS.issubset(cols):
                raise SchemaCompatibilityError(
                    f"checkpoints table has incompatible schema: expected {self._EXPECTED_COLUMNS}, got {cols}"
                )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints ("
            "checkpoint_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload BLOB NOT NULL)"
        )
        self.connection.commit()

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Retrieve a checkpoint by ID."""
        row = self.connection.execute(
            "SELECT payload FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,)
        ).fetchone()
        return None if row is None else Checkpoint.model_validate_json(row[0])

    def close(self) -> None:
        """Close the database connection."""
        self.connection.close()

    def reopen(self) -> None:
        """Reopen the database connection after close."""
        self.connection = sqlite3.connect(str(self.path))

    def compare_and_swap(self, checkpoint: Checkpoint) -> None:
        """Write a checkpoint with compare-and-swap revision check."""
        payload = canonical_bytes(checkpoint)
        with self.connection:
            row = self.connection.execute(
                "SELECT revision FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint.checkpoint_id,),
            ).fetchone()
            current = 0 if row is None else int(row[0])
            if checkpoint.expected_previous_revision != current:
                raise StaleCheckpointError(f"Expected {checkpoint.expected_previous_revision}, found {current}")
            if checkpoint.checkpoint_revision != current + 1:
                raise StaleCheckpointError("Revision must increase by one")
            self.connection.execute(
                "INSERT INTO checkpoints(checkpoint_id, revision, payload) VALUES(?, ?, ?) "
                "ON CONFLICT(checkpoint_id) DO UPDATE SET revision=excluded.revision, "
                "payload=excluded.payload",
                (checkpoint.checkpoint_id, checkpoint.checkpoint_revision, payload),
            )

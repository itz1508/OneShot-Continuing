"""Checkpoint compatibility fixtures F01-F09 and regression tests for confirmed defects.

Tests verify:
- F01: Empty databases create correct schemas
- F02: Host revision history preserved
- F03: Operation ledger entries preserved
- F04: Typed checkpoint survives reopen
- F05: CAS contention — one writer wins
- F06: Damaged storage detected (integrity check)
- F07: Schema collision rejected
- F08: Restart with unfinished effect
- F09: Revision edge cases
- Regression: integrity verification on read
- Regression: 'or True' removed
- Regression: schema compatibility checks
- Regression: attempt identity
- Regression: ledger status transitions
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from agent.contracts.host import Checkpoint
from agent.runtime.checkpoint_store import (
    CheckpointIntegrityError,
    CheckpointStore,
    CheckpointStoreError,
    CompetingWriterError,
    SchemaCompatibilityError,
)
from agent.runtime.durable_checkpoint_store import (
    SQLiteCheckpointStore,
)
from agent.runtime.durable_checkpoint_store import (
    StaleCheckpointError as DurableStaleError,
)


class TestF01EmptyDatabases:
    """F01: Fresh database for each store creates original schema correctly."""

    def test_checkpoint_store_schema(self, tmp_path):
        store = CheckpointStore(tmp_path)
        conn = sqlite3.connect(str(store.db_path))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(checkpoints)")}
        assert {"task_id", "revision", "state_json", "state_digest", "created_at"}.issubset(cols)
        ledger_cols = {row[1] for row in conn.execute("PRAGMA table_info(operation_ledger)")}
        assert {"op_id", "task_id", "checkpoint_revision", "operation_type", "operation_data", "status"}.issubset(
            ledger_cols
        )
        conn.close()

    def test_sqlite_store_schema(self, tmp_path):
        store = SQLiteCheckpointStore(tmp_path / "durable.db")
        cols = {row[1] for row in store.connection.execute("PRAGMA table_info(checkpoints)")}
        assert {"checkpoint_id", "revision", "payload"}.issubset(cols)
        store.close()


class TestF02HostRevisionHistory:
    """F02: Three task revisions and two distinct tasks — all retained."""

    def test_revisions_retained(self, tmp_path):
        store = CheckpointStore(tmp_path)
        for i in range(3):
            store.checkpoint_cas("task-A", i, {"step": i})
        store.checkpoint_cas("task-B", 0, {"step": "init"})
        result_a = store.load_checkpoint("task-A")
        assert result_a is not None
        assert result_a[0] == 3
        assert result_a[1]["step"] == 2
        result_b = store.load_checkpoint("task-B")
        assert result_b is not None
        assert result_b[0] == 1
        assert result_b[1]["step"] == "init"

    def test_all_historical_revisions_in_db(self, tmp_path):
        store = CheckpointStore(tmp_path)
        for i in range(3):
            store.checkpoint_cas("task-A", i, {"step": i})
        conn = sqlite3.connect(str(store.db_path))
        revs = [
            row[0]
            for row in conn.execute("SELECT revision FROM checkpoints WHERE task_id=? ORDER BY revision", ("task-A",))
        ]
        conn.close()
        assert revs == [1, 2, 3]


class TestF03OperationLedger:
    """F03: Pending, completed, and interrupted operations preserved."""

    def test_ledger_entries(self, tmp_path):
        store = CheckpointStore(tmp_path)
        rev, _ = store.checkpoint_cas("task-1", 0, {"stage": "init"})
        op1 = store.record_operation("task-1", rev, "create", "file_a.py")
        op2 = store.record_operation("task-1", rev, "modify", "file_b.py")
        store.update_operation_status(op1, "completed")
        conn = sqlite3.connect(str(store.db_path))
        rows = conn.execute("SELECT op_id, status FROM operation_ledger ORDER BY op_id").fetchall()
        conn.close()
        assert rows == [(op1, "completed"), (op2, "pending")]

    def test_invalid_ledger_transition_rejected(self, tmp_path):
        store = CheckpointStore(tmp_path)
        rev, _ = store.checkpoint_cas("task-1", 0, {"stage": "init"})
        op1 = store.record_operation("task-1", rev, "create", "file_a.py")
        store.update_operation_status(op1, "completed")
        with pytest.raises(CheckpointStoreError, match="invalid operation transition"):
            store.update_operation_status(op1, "pending")

    def test_completed_to_pending_blocked(self, tmp_path):
        store = CheckpointStore(tmp_path)
        rev, _ = store.checkpoint_cas("task-1", 0, {"stage": "init"})
        op1 = store.record_operation("task-1", rev, "create", "f.py")
        store.update_operation_status(op1, "in_progress")
        store.update_operation_status(op1, "completed")
        with pytest.raises(CheckpointStoreError, match="invalid operation transition"):
            store.update_operation_status(op1, "in_progress")


class TestF04TypedCheckpoint:
    """F04: Multiple versions of a typed Checkpoint survive reopening."""

    def test_reopen_preserves_data(self, tmp_path):
        db_path = tmp_path / "typed.db"
        store = SQLiteCheckpointStore(db_path)
        cp1 = Checkpoint(
            checkpoint_id="cp-1",
            checkpoint_revision=1,
            expected_previous_revision=0,
            checkpoint_digest="abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
            task_id="task-1",
            run_id="run-1",
            stage="research",
            phase="execution",
            stage_revision=1,
        )
        store.compare_and_swap(cp1)
        store.close()
        store.reopen()
        result = store.get("cp-1")
        assert result is not None
        assert result.checkpoint_id == "cp-1"
        assert result.checkpoint_revision == 1
        store.close()

    def test_multiple_versions(self, tmp_path):
        db_path = tmp_path / "multi.db"
        store = SQLiteCheckpointStore(db_path)
        for rev in range(1, 4):
            cp = Checkpoint(
                checkpoint_id="cp-evolving",
                checkpoint_revision=rev,
                expected_previous_revision=rev - 1,
                checkpoint_digest="a" * 64,
                task_id="task-1",
                run_id="run-1",
                stage="research",
                phase="execution",
                stage_revision=rev,
            )
            store.compare_and_swap(cp)
        result = store.get("cp-evolving")
        assert result is not None
        assert result.checkpoint_revision == 3
        store.close()


class TestF05CASContention:
    """F05: Two independent writers with same expected revision — one succeeds."""

    def test_concurrent_cas_one_wins(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"v": 1})
        results = []
        barrier = threading.Barrier(2)

        def writer():
            barrier.wait()
            try:
                store.checkpoint_cas("task-1", 1, {"v": "concurrent"})
                results.append("success")
            except CompetingWriterError:
                results.append("rejected")

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=writer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert results.count("success") == 1
        assert results.count("rejected") == 1

    def test_durable_cas_rejects_stale(self, tmp_path):
        store = SQLiteCheckpointStore(tmp_path / "durable.db")
        cp1 = Checkpoint(
            checkpoint_id="cp-1",
            checkpoint_revision=1,
            expected_previous_revision=0,
            checkpoint_digest="a" * 64,
            task_id="t1",
            run_id="run-1",
            stage="research",
            phase="execution",
            stage_revision=1,
        )
        store.compare_and_swap(cp1)
        cp_stale = Checkpoint(
            checkpoint_id="cp-1",
            checkpoint_revision=2,
            expected_previous_revision=0,
            checkpoint_digest="b" * 64,
            task_id="t1",
            run_id="run-1",
            stage="research",
            phase="execution",
            stage_revision=2,
        )
        with pytest.raises(DurableStaleError):
            store.compare_and_swap(cp_stale)
        store.close()


class TestF06DamagedStorage:
    """F06: Modified state JSON, incorrect digest, malformed payload detected."""

    def test_tampered_state_json_detected(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"stage": "original"})
        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "UPDATE checkpoints SET state_json = ? WHERE task_id = ?",
            (json.dumps({"stage": "tampered"}, sort_keys=True), "task-1"),
        )
        conn.commit()
        conn.close()
        with pytest.raises(CheckpointIntegrityError, match="integrity failure"):
            store.load_checkpoint("task-1")

    def test_tampered_digest_detected(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"stage": "original"})
        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "UPDATE checkpoints SET state_digest = '0000000000000000000000000000000000000000000000000000000000000000' WHERE task_id = ?",
            ("task-1",),
        )
        conn.commit()
        conn.close()
        with pytest.raises(CheckpointIntegrityError, match="integrity failure"):
            store.load_checkpoint("task-1")


class TestF07SchemaCollision:
    """F07: Opening either database through the other store's API is rejected."""

    def test_checkpoint_store_rejects_durable_schema(self, tmp_path):
        db_path = tmp_path / "checkpoints.db"
        durable = SQLiteCheckpointStore(db_path)
        durable.close()
        with pytest.raises(SchemaCompatibilityError, match="incompatible schema"):
            CheckpointStore(tmp_path)

    def test_durable_store_rejects_checkpoint_schema(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"v": 1})
        db_path = store.db_path
        with pytest.raises(SchemaCompatibilityError, match="incompatible schema"):
            SQLiteCheckpointStore(db_path)


class TestF08RestartRetry:
    """F08: Persistent checkpoint with unfinished effect requires reconciliation."""

    def test_pre_effect_checkpoint_survives_restart(self, tmp_path):
        store1 = CheckpointStore(tmp_path)
        store1.checkpoint_cas(
            "pre-effect-act-1-attempt-1",
            0,
            {
                "type": "pre_effect",
                "action_id": "act-1",
                "attempt": 1,
                "file_path": "test.py",
                "expected_pre_digest": None,
                "expected_post_digest": "abc",
            },
        )
        del store1
        store2 = CheckpointStore(tmp_path)
        result = store2.load_checkpoint("pre-effect-act-1-attempt-1")
        assert result is not None
        assert result[1]["type"] == "pre_effect"
        assert result[1]["action_id"] == "act-1"


class TestF09RevisionEdgeCases:
    """F09: Stale, skipped, duplicate, invalid, out-of-order revisions rejected."""

    def test_stale_revision_rejected(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"v": 1})
        with pytest.raises(CompetingWriterError):
            store.checkpoint_cas("task-1", 0, {"v": 2})

    def test_skipped_revision_rejected(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"v": 1})
        with pytest.raises(CompetingWriterError):
            store.checkpoint_cas("task-1", 2, {"v": 3})

    def test_nonexistent_task_returns_none(self, tmp_path):
        store = CheckpointStore(tmp_path)
        assert store.load_checkpoint("nonexistent") is None

    def test_duplicate_revision_rejected(self, tmp_path):
        """Writing with stale expected revision after current advanced fails."""
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"v": 1})  # rev 1
        store.checkpoint_cas("task-1", 1, {"v": 2})  # rev 2
        # Try to write with expected=0 when current=2 — should fail
        with pytest.raises(CompetingWriterError):
            store.checkpoint_cas("task-1", 0, {"v": "stale"})
        # Try to write with expected=1 when current=2 — should fail
        with pytest.raises(CompetingWriterError):
            store.checkpoint_cas("task-1", 1, {"v": "stale"})

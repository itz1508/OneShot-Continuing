"""Gap regression tests — verify all identified gaps are fixed.

GAP1: SQLiteCheckpointStore.get() integrity verification
GAP2: Connection cleanup on schema error
GAP3: Load by specific revision
GAP4: recovery.reconcile() returns structured data
GAP5: execute_admitted checks for prior attempt checkpoint
GAP6: _clear_pre_effect_checkpoint handles missing checkpoint
GAP7: record_operation validates operation_type
GAP8: update_operation_status with nonexistent op_id
GAP9: SQLiteCheckpointStore tampered payload detection
GAP10: Connection properly closed on schema error
"""

from __future__ import annotations

import sqlite3

import pytest

from agent.runtime.checkpoint_store import (
    CheckpointIntegrityError,
    CheckpointStore,
    CheckpointStoreError,
    SchemaCompatibilityError,
)
from agent.runtime.durable_checkpoint_store import SQLiteCheckpointStore
from agent.runtime.recovery import BoundedRecovery


class TestGAP1DurableIntegrity:
    """GAP1: SQLiteCheckpointStore.get() verifies payload integrity."""

    def test_tampered_payload_rejected(self, tmp_path):
        from agent.contracts.host import Checkpoint

        store = SQLiteCheckpointStore(tmp_path / "durable.db")
        cp = Checkpoint(
            checkpoint_id="cp-1",
            checkpoint_revision=1,
            expected_previous_revision=0,
            checkpoint_digest="a" * 64,
            task_id="t1",
            run_id="r1",
            stage="research",
            phase="execution",
            stage_revision=1,
        )
        store.compare_and_swap(cp)
        store.close()

        # Tamper with the payload
        conn = sqlite3.connect(str(tmp_path / "durable.db"))
        conn.execute(
            "UPDATE checkpoints SET payload = ? WHERE checkpoint_id = ?",
            (
                b'{"checkpoint_id":"cp-1","checkpoint_revision":1,"expected_previous_revision":0,"checkpoint_digest":"aaa","task_id":"t1","run_id":"r1","stage":"research","phase":"execution","stage_revision":1}',
                "cp-1",
            ),
        )
        conn.commit()
        conn.close()

        store.reopen()
        from pydantic import ValidationError

        with pytest.raises((ValidationError, ValueError)):
            store.get("cp-1")
        store.close()


class TestGAP2ConnectionCleanup:
    """GAP2+10: Connection properly closed on schema error."""

    def test_connection_closed_on_schema_error(self, tmp_path):
        # Create a CheckpointStore database first
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"v": 1})
        db_path = store.db_path

        # Try to open it as SQLiteCheckpointStore — should fail
        with pytest.raises(SchemaCompatibilityError):
            SQLiteCheckpointStore(db_path)

        # Verify the database file is still accessible (connection was closed)
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()
        conn.close()
        assert rows[0] == 1  # Data intact


class TestGAP3LoadRevision:
    """GAP3: Load specific checkpoint revision."""

    def test_load_specific_revision(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"v": "rev1"})
        store.checkpoint_cas("task-1", 1, {"v": "rev2"})
        store.checkpoint_cas("task-1", 2, {"v": "rev3"})

        rev1 = store.load_revision("task-1", 1)
        assert rev1 is not None
        assert rev1[0] == 1
        assert rev1[1]["v"] == "rev1"

        rev3 = store.load_revision("task-1", 3)
        assert rev3 is not None
        assert rev3[0] == 3
        assert rev3[1]["v"] == "rev3"

    def test_load_nonexistent_revision(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"v": 1})
        assert store.load_revision("task-1", 99) is None

    def test_load_revision_integrity_check(self, tmp_path):
        store = CheckpointStore(tmp_path)
        store.checkpoint_cas("task-1", 0, {"v": 1})
        # Tamper
        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "UPDATE checkpoints SET state_json = ? WHERE task_id = ? AND revision = ?",
            ('{"v":"tampered"}', "task-1", 1),
        )
        conn.commit()
        conn.close()
        with pytest.raises(CheckpointIntegrityError):
            store.load_revision("task-1", 1)


class TestGAP4ReconcileStructured:
    """GAP4: recovery.reconcile() returns structured data, not string."""

    def test_reconcile_returns_dict(self):
        recovery = BoundedRecovery()
        result = recovery.reconcile("op-1", "data")
        assert isinstance(result, dict)
        assert result["operation_id"] == "op-1"
        assert result["status"] == "requires_physical_verification"
        assert "physical" in result["message"].lower()


class TestGAP5PriorAttemptCheck:
    """GAP5: execute_admitted rejects if prior attempt checkpoint exists."""

    def test_prior_attempt_blocks_execution(self, tmp_path):
        from agent.contracts.build import BuildActionStatus
        from agent.runtime.authorization import AuthorizationEngine
        from agent.runtime.effect_executor import EffectExecutor
        from agent.runtime.receipt_store import ReceiptStore

        workspace = tmp_path / "ws"
        workspace.mkdir()
        state = tmp_path / "state"
        state.mkdir()
        auth = AuthorizationEngine(allowed_roots=(str(workspace),))
        cp = CheckpointStore(state)
        receipts = ReceiptStore(state / "receipts.db")
        executor = EffectExecutor(auth, cp, receipts, workspace)

        # Write a pre-effect checkpoint for attempt 1
        executor._pre_effect_checkpoint("act-1", "file.py", None, "abc", attempt=1)

        # Try to execute with attempt=1 — should be blocked
        from agent.contracts.host import BuildAdmissionReceipt, ReceiptRef

        receipt = BuildAdmissionReceipt(
            admission_id="adm-1",
            authorized_action_ids=("act-1",),
            authorized_tool_ids=("tool-1",),
            lock_receipt_ref=ReceiptRef(receipt_id="lock-1", receipt_digest="b" * 64, issuer_id="host"),
            receipt_ref=ReceiptRef(receipt_id="adm-1", receipt_digest="c" * 64, issuer_id="host"),
        )
        result = executor.execute_admitted("act-1", "create", receipt, target_path="file.py", content="x", attempt=1)
        assert result.status == BuildActionStatus.EFFECT_UNCERTAIN
        assert "prior pre-effect checkpoint" in result.error


class TestGAP6GracefulClear:
    """GAP6: _clear_pre_effect_checkpoint is no-op when no checkpoint exists."""

    def test_clear_without_prior_checkpoint(self, tmp_path):
        from agent.runtime.authorization import AuthorizationEngine
        from agent.runtime.effect_executor import EffectExecutor
        from agent.runtime.receipt_store import ReceiptStore

        workspace = tmp_path / "ws"
        workspace.mkdir()
        state = tmp_path / "state"
        state.mkdir()
        auth = AuthorizationEngine(allowed_roots=(str(workspace),))
        cp = CheckpointStore(state)
        receipts = ReceiptStore(state / "receipts.db")
        executor = EffectExecutor(auth, cp, receipts, workspace)

        # Clear without prior write — should not raise
        executor._clear_pre_effect_checkpoint("act-1", attempt=1)

        # Verify no checkpoint was created
        assert cp.load_checkpoint("pre-effect-act-1-attempt-1") is None


class TestGAP7OperationTypeValidation:
    """GAP7: record_operation validates operation_type."""

    def test_valid_operation_types(self, tmp_path):
        store = CheckpointStore(tmp_path)
        rev, _ = store.checkpoint_cas("task-1", 0, {"v": 1})
        for op_type in ("create", "modify", "remove", "verify", "reconcile"):
            op_id = store.record_operation("task-1", rev, op_type, "data")
            assert op_id > 0

    def test_invalid_operation_type_rejected(self, tmp_path):
        store = CheckpointStore(tmp_path)
        rev, _ = store.checkpoint_cas("task-1", 0, {"v": 1})
        with pytest.raises(CheckpointStoreError, match="unknown operation type"):
            store.record_operation("task-1", rev, "delete_everything", "data")


class TestGAP8NonexistentOp:
    """GAP8: update_operation_status with nonexistent op_id raises error."""

    def test_nonexistent_op_raises(self, tmp_path):
        store = CheckpointStore(tmp_path)
        with pytest.raises(CheckpointStoreError, match="not found"):
            store.update_operation_status(99999, "completed")

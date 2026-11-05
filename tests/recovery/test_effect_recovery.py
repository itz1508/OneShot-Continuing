"""Recovery and chaos fixtures — effect executor under crash conditions.

Tests exercise real persisted state and EffectExecutor, not synthetic
recovery-status strings. Scenarios:
- Interruption before/after pre-effect checkpoint
- Post-image digest mismatch
- Competing processes (CAS)
- Same action across different attempts
- Missing/altered file after restart
- No repeated physical side effect
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent.contracts.build import BuildActionStatus
from agent.contracts.host import BuildAdmissionReceipt, ReceiptRef
from agent.runtime.authorization import AuthorizationEngine
from agent.runtime.checkpoint_store import CheckpointStore, CompetingWriterError
from agent.runtime.effect_executor import EffectExecutor
from agent.runtime.receipt_store import ReceiptStore

VALID_DIGEST = "a" * 64


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def state_root(tmp_path: Path) -> Path:
    sr = tmp_path / "state"
    sr.mkdir()
    return sr


@pytest.fixture()
def executor(workspace: Path, state_root: Path) -> EffectExecutor:
    auth = AuthorizationEngine(allowed_roots=(str(workspace),))
    checkpoints = CheckpointStore(state_root)
    receipts = ReceiptStore(state_root / "receipts.db")
    return EffectExecutor(auth, checkpoints, receipts, workspace)


def _make_receipt(action_id: str) -> BuildAdmissionReceipt:
    """Create a minimal valid admission receipt for testing."""
    return BuildAdmissionReceipt(
        admission_id=f"adm-{action_id}",
        authorized_action_ids=(action_id,),
        authorized_tool_ids=("tool-1",),
        lock_receipt_ref=ReceiptRef(receipt_id="lock-1", receipt_digest="b" * 64, issuer_id="host"),
        receipt_ref=ReceiptRef(receipt_id="adm-1", receipt_digest="c" * 64, issuer_id="host"),
    )


class TestPreEffectInterruption:
    """Interruption before pre-effect checkpoint — no unrecorded operation assumed completed."""

    def test_no_checkpoint_no_effect(self, executor: EffectExecutor, workspace: Path):
        """If no pre-effect checkpoint exists, effect did not start."""
        checkpoint = executor._has_pre_effect_checkpoint("act-1")
        assert checkpoint is None


class TestPostCheckpointInterruption:
    """Interruption after durable pre-effect checkpoint — pending state survives restart."""

    def test_pre_effect_checkpoint_survives_restart(self, workspace: Path, state_root: Path):
        auth = AuthorizationEngine(allowed_roots=(str(workspace),))
        cp1 = CheckpointStore(state_root)
        receipts = ReceiptStore(state_root / "receipts.db")
        exec1 = EffectExecutor(auth, cp1, receipts, workspace)

        # Create a file, write pre-effect checkpoint
        target = workspace / "test.py"
        target.write_text("original")
        pre_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        new_content = "modified"
        expected_post = hashlib.sha256(new_content.encode()).hexdigest()

        exec1._pre_effect_checkpoint("act-1", "test.py", pre_digest, expected_post, attempt=1)

        # Simulate crash — create new executor with same stores
        cp2 = CheckpointStore(state_root)
        receipts2 = ReceiptStore(state_root / "receipts.db")
        exec2 = EffectExecutor(auth, cp2, receipts2, workspace)

        # Pre-effect checkpoint should still exist
        checkpoint = exec2._has_pre_effect_checkpoint("act-1", attempt=1)
        assert checkpoint is not None
        assert checkpoint["type"] == "pre_effect"
        assert checkpoint["action_id"] == "act-1"
        assert checkpoint["file_path"] == "test.py"


class TestPostEffectInterruption:
    """Interruption after filesystem effect but before completion checkpoint."""

    def test_reconcile_completed_effect(self, workspace: Path, state_root: Path):
        auth = AuthorizationEngine(allowed_roots=(str(workspace),))
        cp1 = CheckpointStore(state_root)
        receipts = ReceiptStore(state_root / "receipts.db")
        exec1 = EffectExecutor(auth, cp1, receipts, workspace)

        target = workspace / "file.py"
        target.write_text("old")
        pre_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        new_content = "new content"
        expected_post = hashlib.sha256(new_content.encode()).hexdigest()

        # Write pre-effect checkpoint
        exec1._pre_effect_checkpoint("act-1", "file.py", pre_digest, expected_post, attempt=1)
        # Simulate: file was actually written but completion checkpoint not recorded
        target.write_text(new_content)

        # Crash — new executor
        cp2 = CheckpointStore(state_root)
        receipts2 = ReceiptStore(state_root / "receipts.db")
        exec2 = EffectExecutor(auth, cp2, receipts2, workspace)

        result = exec2.reconcile_effect("act-1", "file.py", expected_post, attempt=1)
        assert result.status == BuildActionStatus.COMPLETED
        assert result.post_image_digest == expected_post

    def test_reconcile_digest_mismatch_stays_uncertain(self, workspace: Path, state_root: Path):
        auth = AuthorizationEngine(allowed_roots=(str(workspace),))
        cp1 = CheckpointStore(state_root)
        receipts = ReceiptStore(state_root / "receipts.db")
        exec1 = EffectExecutor(auth, cp1, receipts, workspace)

        target = workspace / "file.py"
        target.write_text("old")
        pre_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        expected_post = hashlib.sha256(b"expected").hexdigest()

        exec1._pre_effect_checkpoint("act-1", "file.py", pre_digest, expected_post, attempt=1)
        # File was partially written — content doesn't match expected
        target.write_text("partial")

        cp2 = CheckpointStore(state_root)
        receipts2 = ReceiptStore(state_root / "receipts.db")
        exec2 = EffectExecutor(auth, cp2, receipts2, workspace)

        result = exec2.reconcile_effect("act-1", "file.py", expected_post, attempt=1)
        assert result.status == BuildActionStatus.EFFECT_UNCERTAIN
        assert "digest mismatch" in result.error


class TestCompetingProcesses:
    """Competing processes — one valid CAS update, no lost history."""

    def test_concurrent_cas_one_succeeds(self, state_root: Path):
        import threading

        store = CheckpointStore(state_root)
        store.checkpoint_cas("task-1", 0, {"v": 1})
        results = []
        barrier = threading.Barrier(2)

        def writer():
            barrier.wait()
            try:
                store.checkpoint_cas("task-1", 1, {"v": "concurrent"})
                results.append("ok")
            except CompetingWriterError:
                results.append("fail")

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=writer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert results.count("ok") == 1
        assert results.count("fail") == 1


class TestAttemptIdentity:
    """Same action across different attempts — exact attempt identity preserved."""

    def test_different_attempts_have_distinct_checkpoints(self, workspace: Path, state_root: Path):
        auth = AuthorizationEngine(allowed_roots=(str(workspace),))
        cp = CheckpointStore(state_root)
        receipts = ReceiptStore(state_root / "receipts.db")
        executor = EffectExecutor(auth, cp, receipts, workspace)

        # Write pre-effect checkpoint for attempt 1
        executor._pre_effect_checkpoint("act-1", "file.py", None, "d1", attempt=1)
        # Write pre-effect checkpoint for attempt 2
        executor._pre_effect_checkpoint("act-1", "file.py", None, "d2", attempt=2)

        # Both should exist independently
        cp1 = executor._has_pre_effect_checkpoint("act-1", attempt=1)
        cp2 = executor._has_pre_effect_checkpoint("act-1", attempt=2)
        assert cp1 is not None
        assert cp2 is not None
        assert cp1["attempt"] == 1
        assert cp2["attempt"] == 2
        assert cp1["expected_post_digest"] == "d1"
        assert cp2["expected_post_digest"] == "d2"


class TestMissingFileAfterRestart:
    """Missing or altered file after restart — correct distinction between uncertainty and completion."""

    def test_missing_file_with_expected_removal_completes(self, workspace: Path, state_root: Path):
        auth = AuthorizationEngine(allowed_roots=(str(workspace),))
        cp1 = CheckpointStore(state_root)
        receipts = ReceiptStore(state_root / "receipts.db")
        exec1 = EffectExecutor(auth, cp1, receipts, workspace)

        target = workspace / "to_delete.py"
        target.write_text("content")
        pre_digest = hashlib.sha256(target.read_bytes()).hexdigest()

        # Pre-effect checkpoint for removal (expected_post=None)
        exec1._pre_effect_checkpoint("act-1", "to_delete.py", pre_digest, None, attempt=1)
        # Simulate: file was deleted before crash
        target.unlink()

        cp2 = CheckpointStore(state_root)
        receipts2 = ReceiptStore(state_root / "receipts.db")
        exec2 = EffectExecutor(auth, cp2, receipts2, workspace)

        result = exec2.reconcile_effect("act-1", "to_delete.py", None, attempt=1)
        assert result.status == BuildActionStatus.COMPLETED

    def test_missing_file_with_expected_content_fails(self, workspace: Path, state_root: Path):
        auth = AuthorizationEngine(allowed_roots=(str(workspace),))
        cp1 = CheckpointStore(state_root)
        receipts = ReceiptStore(state_root / "receipts.db")
        exec1 = EffectExecutor(auth, cp1, receipts, workspace)

        target = workspace / "file.py"
        target.write_text("content")
        pre_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        expected_post = hashlib.sha256(b"new content").hexdigest()

        exec1._pre_effect_checkpoint("act-1", "file.py", pre_digest, expected_post, attempt=1)
        # File deleted before crash
        target.unlink()

        cp2 = CheckpointStore(state_root)
        receipts2 = ReceiptStore(state_root / "receipts.db")
        exec2 = EffectExecutor(auth, cp2, receipts2, workspace)

        result = exec2.reconcile_effect("act-1", "file.py", expected_post, attempt=1)
        assert result.status == BuildActionStatus.EFFECT_UNCERTAIN


class TestNoRepeatedSideEffect:
    """Reconciliation repeated — no repeated physical side effect."""

    def test_reconcile_twice_does_not_duplicate(self, workspace: Path, state_root: Path):
        auth = AuthorizationEngine(allowed_roots=(str(workspace),))
        cp1 = CheckpointStore(state_root)
        receipts = ReceiptStore(state_root / "receipts.db")
        exec1 = EffectExecutor(auth, cp1, receipts, workspace)

        target = workspace / "file.py"
        target.write_text("old")
        pre_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        new_content = "final"
        expected_post = hashlib.sha256(new_content.encode()).hexdigest()

        exec1._pre_effect_checkpoint("act-1", "file.py", pre_digest, expected_post, attempt=1)
        target.write_text(new_content)

        cp2 = CheckpointStore(state_root)
        receipts2 = ReceiptStore(state_root / "receipts.db")
        exec2 = EffectExecutor(auth, cp2, receipts2, workspace)

        # First reconciliation — should complete and clear checkpoint
        result1 = exec2.reconcile_effect("act-1", "file.py", expected_post, attempt=1)
        assert result1.status == BuildActionStatus.COMPLETED

        # Second reconciliation — no pre-effect checkpoint, standard path
        result2 = exec2.reconcile_effect("act-1", "file.py", expected_post, attempt=1)
        assert result2.status == BuildActionStatus.COMPLETED
        assert result2.post_image_digest == expected_post

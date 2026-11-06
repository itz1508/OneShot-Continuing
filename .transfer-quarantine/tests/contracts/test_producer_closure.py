"""Source producers enforce concrete host boundaries, not just symbol presence."""

from pathlib import Path

import pytest

from agent.contracts.build import BuildActionStatus
from agent.contracts.build_schedule import BuildBatch, BuildTask, BuildWave, VerifiedWaveResult
from agent.contracts.common import ArtifactRef
from agent.contracts.host import ReceiptRef
from agent.contracts.research import ResearchIntent
from agent.contracts.task_todo import TaskTodo
from agent.research_catalog import ResearchCatalog
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.authorization import AuthorizationEngine
from agent.runtime.build_admission import BuildAdmission
from agent.runtime.canonical_serialization import SERIALIZER_PROFILE, digest_raw
from agent.runtime.checkpoint_store import CheckpointStore
from agent.runtime.effect_executor import EffectExecutor
from agent.runtime.receipt_store import ReceiptStore
from agent.runtime.runtime_root_registry import RuntimeRootRegistry


def move_wave(source_digest: str) -> BuildWave:
    todo = TaskTodo(
        todo_id="move-1",
        todo_revision=1,
        title="Move",
        objective="Move admitted file",
        source_action_ids=("move-1",),
        authorized_paths=("source.txt", "target.txt"),
        expected_preimages={"source.txt": source_digest, "target.txt": None},
        instructions=("Move source to target",),
        expected_result="target contains source",
        recovery_requirements=("reconcile source and target",),
    )
    return BuildWave(
        wave_id="wave-1",
        wave_index=1,
        batches=(BuildBatch(batch_id="batch-1", tasks=(BuildTask(task_id="move-1", todo=todo),)),),
        expected_preimages=todo.expected_preimages,
    )


def move_executor(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    receipts = ReceiptStore(state)
    _, lock_digest = receipts.issue_verified("lock-1", "host", "lock-subject")
    admission = BuildAdmission(receipts).admit(
        "move-1",
        ReceiptRef(receipt_id="lock-1", receipt_digest=lock_digest, issuer_id="host"),
        ("move-1",),
        "lock-subject",
    )
    executor = EffectExecutor(
        AuthorizationEngine(allowed_roots=(str(workspace), str(state))),
        CheckpointStore(state),
        receipts,
        workspace,
    )
    return workspace, executor, admission


def test_move_is_atomic_and_pinned_to_source_and_absent_target(tmp_path):
    workspace, executor, admission = move_executor(tmp_path)
    (workspace / "source.txt").write_bytes(b"original")
    expected = digest_raw(b"original")
    wave = move_wave(expected)
    (workspace / "source.txt").write_bytes(b"changed")
    stale = executor.execute_admitted(
        "move-1",
        "move",
        admission,
        source_path="source.txt",
        target_path="target.txt",
        expected_source_digest=expected,
        wave=wave,
    )
    assert stale.status is BuildActionStatus.BLOCKED
    assert not (workspace / "target.txt").exists()
    (workspace / "source.txt").write_bytes(b"original")
    moved = executor.execute_admitted(
        "move-1",
        "move",
        admission,
        source_path="source.txt",
        target_path="target.txt",
        expected_source_digest=expected,
        wave=wave,
    )
    assert moved.status is BuildActionStatus.COMPLETED
    assert not (workspace / "source.txt").exists()
    assert (workspace / "target.txt").read_bytes() == b"original"


def test_move_reconciles_crash_after_replace(tmp_path, monkeypatch):
    workspace, executor, admission = move_executor(tmp_path)
    (workspace / "source.txt").write_bytes(b"original")
    expected = digest_raw(b"original")
    wave = move_wave(expected)

    def interrupted(_action_id):
        raise RuntimeError("crash after replace")

    monkeypatch.setattr(executor, "_clear_pre_effect_checkpoint", interrupted)
    result = executor.execute_admitted(
        "move-1",
        "move",
        admission,
        source_path="source.txt",
        target_path="target.txt",
        expected_source_digest=expected,
        wave=wave,
    )
    assert result.status is BuildActionStatus.EFFECT_UNCERTAIN
    restarted = EffectExecutor(executor._auth, executor._checkpoints, executor._receipts, workspace)
    reconciled = restarted.reconcile_effect("move-1", "source.txt", expected)
    assert reconciled.status is BuildActionStatus.COMPLETED
    assert (workspace / "target.txt").read_bytes() == b"original"


def test_later_wave_requires_accepted_prior_result_and_rechecks_preimage(tmp_path):
    workspace, executor, admission = move_executor(tmp_path)
    (workspace / "source.txt").write_bytes(b"original")
    expected = digest_raw(b"original")
    prior = VerifiedWaveResult(
        wave_id="prior-wave",
        accepted=True,
        output_digests={"source.txt": expected, "target.txt": None},
    )
    artifacts = ArtifactStore(tmp_path / "state")
    digest = artifacts.put_immutable(prior, "prior-wave-result", 1, "verified_wave_result", "1.0")
    prior_ref = ArtifactRef(
        artifact_id="prior-wave-result",
        artifact_revision=1,
        artifact_digest=digest,
        contract_id="verified_wave_result",
        contract_version="1.0",
        serializer_profile=SERIALIZER_PROFILE,
    )
    _, receipt_digest = executor._receipts.issue_verified("prior-wave-receipt", "host", f"verified_wave:{digest}")
    receipt_ref = ReceiptRef(receipt_id="prior-wave-receipt", receipt_digest=receipt_digest, issuer_id="host")
    first = move_wave(expected)
    wave = first.model_copy(
        update={
            "wave_index": 2,
            "previous_wave_result_ref": prior_ref,
            "previous_wave_receipt_ref": receipt_ref,
        }
    )
    without_artifacts = executor.execute_admitted(
        "move-1",
        "move",
        admission,
        source_path="source.txt",
        target_path="target.txt",
        expected_source_digest=expected,
        wave=wave,
    )
    assert without_artifacts.status is BuildActionStatus.BLOCKED

    executor._artifacts = artifacts
    (workspace / "source.txt").write_bytes(b"drifted")
    drifted = executor.execute_admitted(
        "move-1",
        "move",
        admission,
        source_path="source.txt",
        target_path="target.txt",
        expected_source_digest=expected,
        wave=wave,
    )
    assert drifted.status is BuildActionStatus.BLOCKED
    (workspace / "source.txt").write_bytes(b"original")
    completed = executor.execute_admitted(
        "move-1",
        "move",
        admission,
        source_path="source.txt",
        target_path="target.txt",
        expected_source_digest=expected,
        wave=wave,
    )
    assert completed.status is BuildActionStatus.COMPLETED


def test_runtime_roots_reject_unregistered_or_escaping_paths(tmp_path):
    roots = RuntimeRootRegistry()
    roots.register("runs", tmp_path)
    assert roots.resolve("runs", "task-1") == tmp_path / "task-1"
    with pytest.raises(ValueError, match="not registered"):
        roots.resolve("other", "task-1")
    with pytest.raises(ValueError, match="invalid runtime path"):
        roots.resolve("runs", "..")


def test_catalog_lineage_binds_actual_synthetic_source():
    catalog = ResearchCatalog()
    match = catalog.match(ResearchIntent.INVESTIGATE_QUESTION)
    lineage = catalog.lineage_for("input-1", match)
    assert lineage.input_id == "input-1"
    assert lineage.catalog_id == match.catalog_id
    assert lineage.is_synthetic is True
    assert len(lineage.source_digest) == 64

"""Connected host integration fixture: Planning repair through actual filesystem Build.

This is a synthetic repository fixture, not a production admission acceptance.
The legacy PackageLock / BuildAdmission route does not yet demand a Scanner
pass receipt, trusted FreezeReceipt or a validated Fixture/Chaos result.
Tests below prove the current execution path while retaining that P0 limitation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from agent.contracts.build import BuildActionStatus, BuildRecord
from agent.contracts.build_schedule import BuildBatch, BuildTask, BuildWave, VerifiedWaveResult
from agent.contracts.build_validation import BuildValidationRecord, E2EResult, ObservedCriterionResult
from agent.contracts.build_validation import CriterionResult as VerificationResult
from agent.contracts.common import ArtifactRef
from agent.contracts.host import ReceiptRef
from agent.contracts.planning import PlanningRecord
from agent.contracts.scanner import CriterionValidity, ScannerOutcome, ScannerResult
from agent.contracts.task_todo import TaskTodo
from agent.runtime.authorization import Capability
from agent.runtime.build_admission import BuildAdmission
from agent.runtime.canonical_serialization import SERIALIZER_PROFILE, digest_raw
from agent.runtime.controller import HostController, Stage, TransitionError
from agent.runtime.effect_executor import EffectExecutor
from agent.runtime.package_lock import PackageLock
from tests.e2e.test_real_workflow import _advance_with_receipt
from tests.fixtures.structural_gap import build_gap_inputs
from tests.scanner.test_decision_trace import artifact_ref, make_planning_record, revised_record


class Evidence(BaseModel):
    name: str


def store_record(host: HostController, artifact_id: str, model: BaseModel, contract_id: str) -> ArtifactRef:
    digest = host.artifact_store.put_immutable(model, artifact_id, 1, contract_id, "1.0")
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_revision=1,
        artifact_digest=digest,
        contract_id=contract_id,
        contract_version="1.0",
        serializer_profile=SERIALIZER_PROFILE,
    )


def task(action_id: str, path: str, dependencies: tuple[str, ...] = ()) -> TaskTodo:
    return TaskTodo(
        todo_id=action_id,
        todo_revision=1,
        title=f"Implement {action_id}",
        objective=f"Create {path}",
        source_action_ids=(action_id,),
        dependency_todo_ids=dependencies,
        authorized_paths=(path,),
        expected_preimages={path: None},
        instructions=(f"Create {path} from admitted specification",),
        expected_result=f"Verified file {path}",
        recovery_requirements=("reconcile exact effects",),
    )


def test_planning_repair_revalidation_and_real_build_effects(tmp_path: Path) -> None:
    """Real analyzer, Scanner, CAS, lock, admission, waves, effects and E2E observation."""
    workspace = tmp_path / "workspace"
    host = HostController(tmp_path / "runtime", workspace_root=workspace)
    host.init_task("task-001", "run-001")
    _advance_with_receipt(host, "task-001", "run-001", Stage.RESEARCH)
    _advance_with_receipt(host, "task-001", "run-001", Stage.AUDIT_DISCOVERY)
    assert host.get_state("task-001").current_stage is Stage.PLANNING

    research = store_record(host, "research-upstream", Evidence(name="synthetic research"), "research")
    audit = store_record(host, "audit-upstream", Evidence(name="synthetic audit"), "audit")
    record = make_planning_record().model_copy(update={"audit_ref": audit})
    original = store_record(host, "roundtrip-plan", record, "planning")
    request, runner = build_gap_inputs(host)
    request = request.model_copy(update={"candidate_specification_ref": original})
    gap_1 = host.run_structural_gap_analysis(request, walking_skeleton_runner=runner)
    assert gap_1.completion_receipt_ref is not None
    observed_events: list[dict[str, object]] = []
    blocked = host.scan_planning_candidate(
        "task-001",
        "run-001",
        original,
        "fixture-repository",
        ("dependency_readiness",),
        gap_1.result_ref,
        gap_1.completion_receipt_ref,
        on_event=observed_events.append,
    )
    assert blocked.outcome is ScannerOutcome.BLOCKED
    assert blocked.findings
    assert "scanner_finding" in [event["type"] for event in observed_events]
    blocked_digest = host.artifact_store.get_digest(blocked.request_id, 1)
    assert blocked_digest is not None
    blocked_ref = artifact_ref(blocked.request_id, 1, blocked_digest, "scanner_result")

    host.authorization.grant("planner", Capability.WRITE, "draft-plan:task-001")
    repaired = host.repair_planning_draft(
        "task-001", "run-001", original, blocked_ref, revised_record(record), ("consumer",)
    )
    assert repaired.artifact_revision == 2
    assert host.artifact_store.get_verified(original.artifact_id, original.artifact_revision)

    # A prior gap receipt is immutable but must not authorize a changed candidate.
    with pytest.raises(TransitionError, match="different candidate"):
        host.scan_planning_candidate(
            "task-001",
            "run-001",
            repaired,
            "fixture-repository",
            ("dependency_readiness",),
            gap_1.result_ref,
            gap_1.completion_receipt_ref,
        )

    request_2 = request.model_copy(update={"candidate_specification_ref": repaired, "request_revision": 2})
    gap_2 = host.run_structural_gap_analysis(request_2, walking_skeleton_runner=runner)
    assert gap_2.completion_receipt_ref is not None
    checked = host.scan_planning_candidate(
        "task-001",
        "run-001",
        repaired,
        "fixture-repository",
        ("dependency_readiness",),
        gap_2.result_ref,
        gap_2.completion_receipt_ref,
        on_event=observed_events.append,
    )
    assert checked.outcome is ScannerOutcome.PASS
    assert checked.trace_steps
    assert all(step.criterion_validity is CriterionValidity.VALID for step in checked.trace_steps)
    stored_scan = ScannerResult.model_validate_json(host.artifact_store.get_verified(checked.request_id, 1))
    assert stored_scan.candidate_ref == repaired
    assert stored_scan.requested_capabilities == ("dependency_readiness",)

    # Current legacy route accepts an immutable revised plan but cannot prove
    # the Freeze/Scanner approval chain: this is explicitly NOT Build readiness.
    revised = PlanningRecord.model_validate_json(host.artifact_store.get_verified(repaired.artifact_id, 2))
    lock = PackageLock(host.artifact_store, host.receipt_store).lock("roundtrip", research, audit, repaired)
    lock_subject = f"{research.artifact_digest}:{audit.artifact_digest}:{repaired.artifact_digest}"
    admission = BuildAdmission(host.receipt_store, host.artifact_store).admit(
        "roundtrip",
        lock.receipt_ref,
        ("producer", "consumer"),
        lock_subject,
        build_spec=revised.candidate.build_spec,
        package_lock=lock,
    )
    assert admission.authorized_action_ids == ("producer", "consumer")

    executor = EffectExecutor(
        host.authorization,
        host.checkpoint_store,
        host.receipt_store,
        workspace,
        host.artifact_store,
    )
    first_todo = task("producer", "producer.py")
    first_wave = BuildWave(
        wave_id="wave-1",
        wave_index=1,
        batches=(BuildBatch(batch_id="batch-1", tasks=(BuildTask(task_id="producer", todo=first_todo),)),),
        expected_preimages=first_todo.expected_preimages,
    )
    first = executor.execute_admitted(
        "producer",
        "create",
        admission,
        target_path="producer.py",
        content="value = 1\n",
        wave=first_wave,
    )
    assert first.status is BuildActionStatus.COMPLETED
    assert (workspace / "producer.py").read_text() == "value = 1\n"

    prior = VerifiedWaveResult(
        wave_id="wave-1",
        accepted=True,
        output_digests={"producer.py": digest_raw(b"value = 1\n"), "consumer.py": None},
    )
    prior_ref = store_record(host, "wave-1-result", prior, "verified_wave_result")
    _, prev_digest = host.receipt_store.issue_verified(
        "wave-1-receipt", "host", f"verified_wave:{prior_ref.artifact_digest}"
    )
    second_todo = task("consumer", "consumer.py", ("producer",))
    second_wave = BuildWave(
        wave_id="wave-2",
        wave_index=2,
        batches=(BuildBatch(batch_id="batch-2", tasks=(BuildTask(task_id="consumer", todo=second_todo),)),),
        expected_preimages=second_todo.expected_preimages,
        previous_wave_result_ref=prior_ref,
        previous_wave_receipt_ref=ReceiptRef(receipt_id="wave-1-receipt", receipt_digest=prev_digest, issuer_id="host"),
    )
    second = executor.execute_admitted(
        "consumer",
        "create",
        admission,
        target_path="consumer.py",
        content="from producer import value\nanswer = value + 1\n",
        wave=second_wave,
    )
    assert second.status is BuildActionStatus.COMPLETED
    assert (workspace / "consumer.py").is_file()

    lock_ref = store_record(host, "roundtrip-lock", lock, "package_lock")
    admission_ref = store_record(host, "roundtrip-admission", admission, "build_admission")
    build = BuildRecord(
        task_id="task-001",
        run_id="run-001",
        stage_revision=1,
        lock_ref=lock_ref,
        admission_ref=admission_ref,
        action_executions=(first, second),
    )
    build_ref = store_record(host, "roundtrip-build", build, "build_record")

    # Independent physical observation, not the Builder's own success flag.
    actual = (workspace / "consumer.py").read_bytes()
    expected = b"from producer import value\nanswer = value + 1\n"
    assert actual == expected
    verification = BuildValidationRecord(
        task_id="task-001",
        run_id="run-001",
        stage_revision=1,
        build_ref=build_ref,
        criterion_results=(
            ObservedCriterionResult(
                criterion_id="AC-001",
                observed_result="file bytes observed independently",
                outcome=VerificationResult.VALID,
                independent_observation=digest_raw(actual),
                evidence_refs=(f"artifact:{build_ref.artifact_id}@1",),
            ),
        ),
        e2e_results=(
            E2EResult(
                e2e_id="readback",
                entrypoint="workspace-file-observation",
                exit_code=0,
                outcome=VerificationResult.VALID,
                evidence_refs=(f"sha256:{digest_raw(actual)}",),
            ),
        ),
    )
    verification_ref = store_record(host, "roundtrip-e2e", verification, "build_validation_record")
    assert verification_ref.artifact_digest == host.artifact_store.get_digest("roundtrip-e2e", 1)
    replayed = host.event_store.list("task-001")
    assert any(item["event_type"] == "scanner_repair_completed" for item in replayed)
    assert sum(item["event_type"] == "scanner_completed" for item in replayed) == 2
    assert gap_1.result_ref.artifact_digest != gap_2.result_ref.artifact_digest

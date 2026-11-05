"""Freeze requires exact structural, Scanner, and approval evidence."""

import pytest

from agent.contracts.scanner import ScannerFinding, ScannerOutcome
from agent.runtime.controller import HostController, TransitionError
from agent.runtime.scanner_check_registry import ScannerCheckRegistrySnapshot
from agent.runtime.specification_freezer import FreezeError, SpecificationFreezer
from tests.fixtures.scanner import passing_scan
from tests.fixtures.structural_gap import FixturePayload, passing_gap


def ready_freezer(tmp_path):
    controller = HostController(tmp_path)
    gap = passing_gap(controller)
    scan = passing_scan(controller, gap)
    candidate = gap.result.candidate_specification_ref
    _, approval_digest = controller.receipt_store.issue_verified(
        "approval-candidate", "host", f"approve-freeze:{candidate.artifact_digest}"
    )
    assert gap.completion_receipt_ref is not None
    assert controller.scanner_checks is not None
    args = dict(
        candidate_model=FixturePayload(content="approved candidate"),
        artifact_id=candidate.artifact_id,
        revision=candidate.artifact_revision,
        contract_id=candidate.contract_id,
        contract_version=candidate.contract_version,
        scanner_evidence=scan,
        scanner_check_registry_ref=controller.scanner_checks.ref,
        gap_result_ref=gap.result_ref,
        gap_receipt_ref=gap.completion_receipt_ref,
        task_id="task-001",
        run_id="run-001",
        repository_identity_ref="repo-001",
        authorization_receipt_id="approval-candidate",
        authorization_receipt_digest=approval_digest,
    )
    return SpecificationFreezer(controller.artifact_store, controller.receipt_store), args


def test_freeze_creates_receipt_and_exact_frozen_copy(tmp_path):
    freezer, args = ready_freezer(tmp_path)
    receipt = freezer.freeze(**args)
    assert receipt.candidate_ref.artifact_id == "candidate"
    assert receipt.frozen_ref.artifact_id == "frozen-candidate"
    assert receipt.frozen_ref.artifact_digest == receipt.candidate_ref.artifact_digest
    assert receipt.scanner_receipt_ref == args["scanner_evidence"].receipt_ref


def test_freeze_rejects_changed_candidate_before_writing(tmp_path):
    freezer, args = ready_freezer(tmp_path)
    args["candidate_model"] = FixturePayload(content="different candidate")
    with pytest.raises(FreezeError, match="Planning gates"):
        freezer.freeze(**args)
    assert freezer._store.latest_revision("frozen-candidate") == 0


def test_freeze_rejects_forged_scanner_receipt(tmp_path):
    freezer, args = ready_freezer(tmp_path)
    scan = args["scanner_evidence"]
    args["scanner_evidence"] = scan.model_copy(
        update={"receipt_ref": scan.receipt_ref.model_copy(update={"receipt_digest": "f" * 64})}
    )
    with pytest.raises(FreezeError, match="Scanner pass receipt"):
        freezer.freeze(**args)


def test_freeze_rejects_unverified_approval(tmp_path):
    freezer, args = ready_freezer(tmp_path)
    args["authorization_receipt_digest"] = "f" * 64
    with pytest.raises(FreezeError, match="approval receipt"):
        freezer.freeze(**args)


def test_frozen_copy_cannot_be_overwritten(tmp_path):
    freezer, args = ready_freezer(tmp_path)
    freezer.freeze(**args)
    args["candidate_model"] = FixturePayload(content="v2")
    with pytest.raises(FreezeError):
        freezer.freeze(**args)


def test_host_does_not_issue_pass_receipt_for_unchecked_capability(tmp_path):
    controller = HostController(tmp_path)
    gap = passing_gap(controller)
    passing_scan(controller, gap)
    controller.scanner._detectors.clear()  # simulate a missing registered detector
    assert gap.completion_receipt_ref is not None
    outcome = controller.scan_planning_candidate(
        "task-001",
        "run-001",
        gap.result.candidate_specification_ref,
        "repo-001",
        ("syntax", "types"),
        gap.result_ref,
        gap.completion_receipt_ref,
    )
    assert outcome.result.outcome is ScannerOutcome.BLOCKED
    assert outcome.result.capabilities_not_checked == ("syntax", "types")
    assert outcome.evidence is None


def test_host_rejects_partial_registry_coverage(tmp_path):
    controller = HostController(tmp_path)
    gap = passing_gap(controller)
    passing_scan(controller, gap)
    assert gap.completion_receipt_ref is not None
    with pytest.raises(TransitionError, match="required registry checks"):
        controller.scan_planning_candidate(
            "task-001",
            "run-001",
            gap.result.candidate_specification_ref,
            "repo-001",
            (),
            gap.result_ref,
            gap.completion_receipt_ref,
        )


def test_failed_check_persists_result_without_pass_receipt(tmp_path):
    controller = HostController(tmp_path)
    gap = passing_gap(controller)
    passing_scan(controller, gap)
    controller.scanner._detectors["syntax"] = lambda _: (
        ScannerFinding(finding_id="failure-1", capability="syntax", severity="error", message="invalid syntax"),
    )
    assert gap.completion_receipt_ref is not None
    result = controller.scan_planning_candidate(
        "task-001",
        "run-001",
        gap.result.candidate_specification_ref,
        "repo-001",
        ("syntax", "types"),
        gap.result_ref,
        gap.completion_receipt_ref,
    )
    assert result.result.outcome is ScannerOutcome.FAIL
    assert result.evidence is None
    assert controller.artifact_store.get_verified(result.result_ref.artifact_id, 1)


def test_empty_scanner_registry_is_invalid(tmp_path):
    with pytest.raises(ValueError, match="at least 1 item"):
        ScannerCheckRegistrySnapshot(
            tool_registry_ref=ready_freezer(tmp_path)[1]["scanner_check_registry_ref"], checks=()
        )


def test_freeze_rejects_new_candidate_revision_with_old_scan(tmp_path):
    freezer, args = ready_freezer(tmp_path)
    args["revision"] = 2
    with pytest.raises(FreezeError, match="Planning gates"):
        freezer.freeze(**args)

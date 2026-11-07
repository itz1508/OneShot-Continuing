"""Evidence-linked dependency scanner and bounded Runtime repair tests."""

from __future__ import annotations

import json
from time import perf_counter_ns

import pytest
from pydantic import BaseModel

from agent.contracts.common import ArtifactRef
from agent.contracts.planning import (
    BuildSpecification,
    CandidateSpecification,
    CreateAction,
    PlanningRecord,
)
from agent.contracts.scanner import (
    CriterionResult,
    CriterionValidity,
    ObservationState,
    ScannerOutcome,
    ScannerResult,
    ScannerTraceStep,
)
from agent.contracts.validation.planning import (
    parse_action_dependency_facts,
    scan_action_dependencies,
)
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.authorization import AuthorizationError, Capability
from agent.runtime.controller import HostController, TransitionError
from agent.runtime.scanner_gateway import ScannerGateway


class CandidatePayload(BaseModel):
    actions: list[dict[str, object]]


def artifact_ref(artifact_id: str, revision: int, digest: str, contract_id: str = "planning") -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_revision=revision,
        artifact_digest=digest,
        contract_id=contract_id,
        contract_version="1.0",
        serializer_profile="rfc8785-jcs-sha256-v1",
    )


def test_matched_true_false_and_unknown_observations(tmp_path):
    store = ArtifactStore(tmp_path)
    payload = CandidatePayload(
        actions=[
            {"action_id": "producer", "depends_on": []},
            {"action_id": "consumer", "depends_on": ["producer"]},
        ]
    )
    digest = store.put_immutable(payload, "plan-good", 1, "planning", "1.0")
    gateway = ScannerGateway(store)
    good = gateway.scan_exact(artifact_ref("plan-good", 1, digest), "repo", ("dependency_readiness",))
    assert good.outcome is ScannerOutcome.PASS
    assert all(step.criterion_result is CriterionResult.SATISFIED for step in good.trace_steps)
    assert all(step.criterion_validity is CriterionValidity.VALID for step in good.trace_steps)
    assert all(step.observation_state is ObservationState.KNOWN for step in good.trace_steps)
    assert all(
        step.evidence_refs and step.operator == "equals" and step.expected_value is True for step in good.trace_steps
    )

    bad_payload = payload.model_copy(deep=True)
    bad_payload.actions[1]["depends_on"] = ["absent"]  # one controlled difference
    bad_digest = store.put_immutable(bad_payload, "plan-bad", 1, "planning", "1.0")
    bad = gateway.scan_exact(artifact_ref("plan-bad", 1, bad_digest), "repo", ("dependency_readiness",))
    assert bad.outcome is ScannerOutcome.BLOCKED
    assert len(bad.findings) == 1
    assert bad.trace_steps[-1].observed_value is False
    assert bad.trace_steps[-1].criterion_result is CriterionResult.NOT_SATISFIED
    assert bad.trace_steps[-1].criterion_validity is CriterionValidity.NOT_VALID

    missing = gateway.scan_exact(artifact_ref("missing", 1, "a" * 64), "repo", ("dependency_readiness",))
    assert missing.outcome is ScannerOutcome.BLOCKED
    assert len(missing.evidence_requests) == 1
    assert missing.trace_steps[0].observed_value is None
    assert missing.trace_steps[0].criterion_result is CriterionResult.UNKNOWN
    assert missing.trace_steps[0].criterion_validity is CriterionValidity.NOT_VALID


def test_trace_contract_rejects_unknown_as_valid():
    with pytest.raises(ValueError, match="valid checklist"):
        ScannerTraceStep(
            check_id="dependency_readiness",
            rule_version="1",
            scanner_version="1",
            target_ref="draft@1",
            observation_state=ObservationState.UNKNOWN,
            observed_value=None,
            operator="equals",
            expected_value=True,
            criterion_result=CriterionResult.UNKNOWN,
            criterion_validity=CriterionValidity.VALID,
        )


def test_bounded_cache_equivalence_invalidation_and_timings(capsys):
    raw = json.dumps({"actions": [{"action_id": "a", "depends_on": []}]}).encode()
    other = json.dumps({"actions": [{"action_id": "b", "depends_on": []}]}).encode()
    parse_action_dependency_facts.cache_clear()
    start = perf_counter_ns()
    cold = scan_action_dependencies(raw, "artifact@1", "artifact:artifact@1#digest")
    cold_total = perf_counter_ns() - start
    start = perf_counter_ns()
    warm = scan_action_dependencies(raw, "artifact@1", "artifact:artifact@1#digest")
    warm_total = perf_counter_ns() - start
    assert cold.cache_misses == 1 and cold.cache_hits == 0
    assert warm.cache_hits == 1 and warm.cache_misses == 0
    assert cold.trace_steps == warm.trace_steps
    assert cold.findings == warm.findings
    assert cold.parse_duration_ns >= 0 and warm.parse_duration_ns >= 0
    assert parse_action_dependency_facts("parser-1", raw) == parse_action_dependency_facts("parser-1", raw)
    assert parse_action_dependency_facts("parser-2", raw) == parse_action_dependency_facts("parser-1", raw)
    assert parse_action_dependency_facts("parser-1", other) != parse_action_dependency_facts("parser-1", raw)
    assert parse_action_dependency_facts.cache_info().maxsize == 128
    print(
        f"cache cold_ns={cold_total} warm_ns={warm_total} "
        f"cold_parse_ns={cold.parse_duration_ns} warm_parse_ns={warm.parse_duration_ns} "
        f"hits={warm.cache_hits} misses={cold.cache_misses} equivalent=true"
    )
    assert "equivalent=true" in capsys.readouterr().out


def test_invalid_equality_comparison_is_rejected():
    with pytest.raises(ValueError, match="executed equality"):
        ScannerTraceStep(
            check_id="dependency_readiness",
            rule_version="1",
            scanner_version="1",
            target_ref="draft@1",
            observation_state=ObservationState.KNOWN,
            observed_value=False,
            operator="equals",
            expected_value=True,
            criterion_result=CriterionResult.SATISFIED,
            criterion_validity=CriterionValidity.VALID,
            evidence_refs=("artifact:draft@1",),
        )


def test_unused_threshold_is_absent_in_emitted_trace(tmp_path):
    store = ArtifactStore(tmp_path)
    digest = store.put_immutable(
        CandidatePayload(actions=[{"action_id": "a", "depends_on": []}]),
        "draft",
        1,
        "planning",
        "1.0",
    )
    trace = (
        ScannerGateway(store)
        .scan_exact(artifact_ref("draft", 1, digest), "repo", ("dependency_readiness",))
        .trace_steps[0]
    )
    assert "threshold" not in trace.model_dump(mode="json")


def test_malformed_candidate_emits_unknown_not_false(tmp_path):
    store = ArtifactStore(tmp_path)
    digest = store.put_immutable(
        CandidatePayload(actions=[{"action_id": "a", "depends_on": "invalid"}]),
        "malformed",
        1,
        "planning",
        "1.0",
    )
    result = ScannerGateway(store).scan_exact(artifact_ref("malformed", 1, digest), "repo", ("dependency_readiness",))
    assert result.outcome is ScannerOutcome.BLOCKED
    assert result.capabilities_not_checked == ("dependency_readiness",)
    assert result.trace_steps[0].criterion_result is CriterionResult.UNKNOWN
    assert result.trace_steps[0].observed_value is None
    assert len(result.evidence_requests) == 1
    assert not result.findings


def make_planning_record() -> PlanningRecord:
    action_base = {
        "requirement_ids": ("REQ-001",),
        "acceptance_criteria_ids": ("AC-001",),
        "code_intent_ids": ("intent-1",),
        "preconditions": ("source exists",),
        "validation_steps": ("test dependency",),
        "expected_result": "implemented",
        "recovery_requirement": "restore original",
        "target_conflict_check_ref": "fixture-ref",
    }
    producer = CreateAction(action_id="producer", target_path="producer.py", **action_base)
    consumer = CreateAction(action_id="consumer", target_path="consumer.py", depends_on=("absent",), **action_base)
    return PlanningRecord(
        task_id="task-001",
        run_id="run-001",
        stage_revision=1,
        audit_ref=artifact_ref("audit", 1, "b" * 64, "audit"),
        candidate=CandidateSpecification(
            candidate_id="candidate-001",
            specification_revision=1,
            build_spec=BuildSpecification(
                spec_id="spec-001",
                objective="implement dependencies",
                actions=(producer, consumer),
            ),
        ),
    )


def revised_record(original: PlanningRecord) -> PlanningRecord:
    producer, consumer = original.candidate.build_spec.actions
    fixed = consumer.model_copy(update={"depends_on": ("producer",)})
    specification = original.candidate.build_spec.model_copy(update={"actions": (producer, fixed)})
    candidate = original.candidate.model_copy(update={"specification_revision": 2, "build_spec": specification})
    return original.model_copy(update={"stage_revision": 2, "candidate": candidate})


def make_scanned_controller(tmp_path, monkeypatch):
    controller = HostController(tmp_path)
    record = make_planning_record()
    digest = controller.artifact_store.put_immutable(record, "draft", 1, "planning", "1.0")
    current_ref = artifact_ref("draft", 1, digest)
    # Only the structural gap receipt is substituted; real ArtifactStore and gateway run.
    monkeypatch.setattr(controller, "_verify_structural_gap", lambda *args: None)
    scan = controller.scan_planning_candidate(
        "task-001", "run-001", current_ref, "repo", ("dependency_readiness",), None, None
    )
    assert scan.outcome is ScannerOutcome.BLOCKED
    scan_digest = controller.artifact_store.get_digest(scan.request_id, 1)
    assert scan_digest is not None
    scanned_ref = artifact_ref(scan.request_id, 1, scan_digest, "scanner_result")
    persisted = ScannerResult.model_validate_json(controller.artifact_store.get_verified(scan.request_id, 1))
    assert persisted.trace_steps == scan.trace_steps
    return controller, record, current_ref, scanned_ref


def test_runtime_repair_cas_diff_guard_and_rescan(tmp_path, monkeypatch):
    controller, original, before_ref, scan_ref = make_scanned_controller(tmp_path, monkeypatch)
    updated = revised_record(original)
    with pytest.raises(AuthorizationError):
        controller.repair_planning_draft("task-001", "run-001", before_ref, scan_ref, updated, ("consumer",))
    controller.authorization.grant("planner", Capability.WRITE, "draft-plan:task-001")
    new_ref = controller.repair_planning_draft("task-001", "run-001", before_ref, scan_ref, updated, ("consumer",))
    assert new_ref.artifact_revision == 2
    assert controller.artifact_store.get_verified(before_ref.artifact_id, 1)
    assert (
        PlanningRecord.model_validate_json(controller.artifact_store.get_verified(before_ref.artifact_id, 1))
        == original
    )
    rescanned = controller.scanner.scan_exact(new_ref, "repo", ("dependency_readiness",))
    assert rescanned.outcome is ScannerOutcome.PASS
    assert all(step.criterion_validity is CriterionValidity.VALID for step in rescanned.trace_steps)
    with pytest.raises(TransitionError, match="stale"):
        controller.repair_planning_draft("task-001", "run-001", before_ref, scan_ref, updated, ("consumer",))


@pytest.mark.parametrize("changed_field", ["target_path", "preconditions", "audit_ref"])
def test_repair_rejects_unrelated_nested_or_source_edits(tmp_path, monkeypatch, changed_field):
    controller, original, before_ref, scan_ref = make_scanned_controller(tmp_path, monkeypatch)
    controller.authorization.grant("planner", Capability.WRITE, "draft-plan:task-001")
    updated = revised_record(original)
    if changed_field == "audit_ref":
        updated = updated.model_copy(update={"audit_ref": artifact_ref("different", 1, "c" * 64, "audit")})
    else:
        actions = list(updated.candidate.build_spec.actions)
        actions[1] = actions[1].model_copy(
            update={changed_field: "changed" if changed_field == "target_path" else ("new",)}
        )
        spec = updated.candidate.build_spec.model_copy(update={"actions": tuple(actions)})
        cand = updated.candidate.model_copy(update={"build_spec": spec})
        updated = updated.model_copy(update={"candidate": cand})
    with pytest.raises(TransitionError, match="unrelated"):
        controller.repair_planning_draft("task-001", "run-001", before_ref, scan_ref, updated, ("consumer",))
    assert controller.artifact_store.latest_revision("draft") == 1


def test_repair_rejects_dependency_cycle(tmp_path, monkeypatch):
    controller, original, before_ref, scan_ref = make_scanned_controller(tmp_path, monkeypatch)
    controller.authorization.grant("planner", Capability.WRITE, "draft-plan:task-001")
    proposed = revised_record(original)
    actions = list(proposed.candidate.build_spec.actions)
    actions[1] = actions[1].model_copy(update={"depends_on": ("producer", "consumer")})
    spec = proposed.candidate.build_spec.model_copy(update={"actions": tuple(actions)})
    candidate = proposed.candidate.model_copy(update={"build_spec": spec})
    proposed = proposed.model_copy(update={"candidate": candidate})
    with pytest.raises(TransitionError, match="invalid dependency graph"):
        controller.repair_planning_draft("task-001", "run-001", before_ref, scan_ref, proposed, ("consumer",))
    assert controller.artifact_store.latest_revision("draft") == 1


def test_unavailable_telemetry_exporter_does_not_block_persistence_or_expose_payload(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    import agent.runtime.scanner_telemetry as telemetry

    captured = []

    class FailingExporterSpan:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            raise OSError("simulated unavailable exporter")

    def record_span(name, **attributes):
        captured.append((name, attributes))
        return FailingExporterSpan()

    monkeypatch.setitem(sys.modules, "logfire", SimpleNamespace(span=record_span))
    monkeypatch.setattr(telemetry, "_enabled", True)
    controller, _, _, scan_ref = make_scanned_controller(tmp_path, monkeypatch)
    assert controller.artifact_store.get_verified(scan_ref.artifact_id, 1)
    assert captured == [("scanner.run", {"task_id": "task-001", "run_id": "run-001", "artifact_id": "draft"})]


def test_gap_receipt_remains_mandatory(tmp_path):
    controller = HostController(tmp_path)
    with pytest.raises(TransitionError, match="structural gap"):
        controller.scan_planning_candidate(
            "task-001",
            "run-001",
            artifact_ref("missing", 1, "a" * 64),
            "repo",
            ("dependency_readiness",),
            None,
            None,
        )


def test_disabled_logfire_never_blocks_persistence(tmp_path, monkeypatch):
    import agent.runtime.scanner_telemetry as telemetry

    monkeypatch.setattr(telemetry, "_enabled", False)
    controller, _, _, scan_ref = make_scanned_controller(tmp_path, monkeypatch)
    assert controller.artifact_store.get_verified(scan_ref.artifact_id, 1)
    # Only identifiers are passed to the span, no candidate bytes or evidence.

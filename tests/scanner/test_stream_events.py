"""Live Scanner event projection and single-Host Runtime invocation tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

import agent.contracts.validation.planning as planning
from agent.contracts.scanner import ScannerOutcome
from agent.runtime.authorization import Capability
from agent.runtime.controller import HostController
from tests.scanner.test_decision_trace import artifact_ref, make_planning_record, revised_record


def test_host_emits_durable_check_trace_findings_cache_and_result(tmp_path, monkeypatch):
    host = HostController(tmp_path)
    record = make_planning_record()
    record = record.model_copy(
        update={
            "candidate": record.candidate.model_copy(
                update={
                    "build_spec": record.candidate.build_spec.model_copy(
                        update={"objective": "CONFIDENTIAL_ARTIFACT_CONTENT"}
                    )
                }
            )
        }
    )
    digest = host.artifact_store.put_immutable(record, "draft", 1, "planning", "1.0")
    ref = artifact_ref("draft", 1, digest)
    # Only upstream structural-gap admission is substituted; actual gateway/store/events execute.
    monkeypatch.setattr(host, "_verify_structural_gap", lambda *args: None)

    observed: list[dict[str, object]] = []
    scan = host.scan_planning_candidate(
        record.task_id,
        record.run_id,
        ref,
        "repo",
        ("dependency_readiness",),
        None,
        None,
        on_event=observed.append,
    )
    assert scan.outcome is ScannerOutcome.BLOCKED
    types = [event["type"] for event in observed]
    assert types[0] == "scanner_started"
    assert "scanner_check" in types
    assert "scanner_finding" in types
    assert "scanner_cache_metrics" in types
    assert types[-1] == "scanner_completed"
    assert all(event["detail"]["scan_id"] == scan.request_id for event in observed)
    executed = next(event["detail"] for event in observed if event["type"] == "scanner_check")
    assert executed["operator"] == "equals"
    assert executed["rule_version"] == "2" and executed["scanner_version"] == "2"
    assert executed["observed_value"] is not None and executed["expected_value"] is not None
    assert executed["evidence_refs"] and "threshold" not in executed
    assert [event["sequence"] for event in observed] == sorted(event["sequence"] for event in observed)
    assert any(
        event["detail"]["criterion_result"] == "not_satisfied" for event in observed if event["type"] == "scanner_check"
    )
    recorded = host.event_store.list(record.task_id)
    emitted = [event for event in recorded if event["event_type"] in set(types)]
    assert [event["seq"] for event in emitted] == [event["sequence"] for event in observed]
    assert "CONFIDENTIAL_ARTIFACT_CONTENT" not in json.dumps(observed)
    assert "CONFIDENTIAL_ARTIFACT_CONTENT" not in json.dumps(recorded)
    assert host.artifact_store.get_verified(scan.request_id, 1)

    previous_sequence = observed[-1]["sequence"]
    replay = host.event_store.list(record.task_id)
    assert [event["seq"] for event in replay if event["seq"] > previous_sequence] == []

    # The second invocation still emits executed comparisons and a new immutable result.
    again: list[dict[str, object]] = []
    second = host.scan_planning_candidate(
        record.task_id,
        record.run_id,
        ref,
        "repo",
        ("dependency_readiness",),
        None,
        None,
        on_event=again.append,
    )
    assert second.request_id != scan.request_id
    assert second.trace_steps == scan.trace_steps
    assert any(event["type"] == "scanner_check" for event in again)
    assert again[-1]["detail"]["cache_hits"] >= 1


def test_unknown_evidence_requests_and_authorized_repair_emit_events(tmp_path, monkeypatch):
    host = HostController(tmp_path)
    record = make_planning_record()
    raw_digest = host.artifact_store.put_immutable(record, "draft", 1, "planning", "1.0")
    ref = artifact_ref("draft", 1, raw_digest)
    monkeypatch.setattr(host, "_verify_structural_gap", lambda *args: None)

    # A missing exact artifact is UNKNOWN and produces an evidence request without a finding.
    unknown_events: list[tuple[str, dict[str, object]]] = []
    missing = host.scanner.scan_exact(
        artifact_ref("missing", 1, "a" * 64),
        "repo",
        ("dependency_readiness",),
        on_event=lambda event, detail: unknown_events.append((event, detail)),
    )
    assert missing.outcome is ScannerOutcome.BLOCKED
    assert [event for event, _ in unknown_events] == ["scanner_check", "scanner_evidence_requested"]
    assert unknown_events[0][1]["criterion_result"] == "unknown"

    scan = host.scan_planning_candidate(
        record.task_id, record.run_id, ref, "repo", ("dependency_readiness",), None, None
    )
    scan_digest = host.artifact_store.get_digest(scan.request_id, 1)
    assert scan_digest is not None
    scan_ref = artifact_ref(scan.request_id, 1, scan_digest, "scanner_result")
    host.authorization.grant("planner", Capability.WRITE, "draft-plan:task-001")
    updated = host.repair_planning_draft(
        record.task_id, record.run_id, ref, scan_ref, revised_record(record), ("consumer",)
    )
    assert updated.artifact_revision == 2
    events = host.event_store.list(record.task_id)
    types = [event["event_type"] for event in events]
    assert types.index("scanner_repair_started") < types.index("scanner_repair_completed")
    assert events[-1]["event_type"] == "scanner_repair_completed"


def test_check_events_are_persisted_while_detector_is_still_executing(tmp_path, monkeypatch):
    host = HostController(tmp_path)
    record = make_planning_record()
    producer, consumer = record.candidate.build_spec.actions
    consumer = consumer.model_copy(update={"depends_on": ("producer", "absent")})
    spec = record.candidate.build_spec.model_copy(update={"actions": (producer, consumer)})
    record = record.model_copy(update={"candidate": record.candidate.model_copy(update={"build_spec": spec})})
    digest = host.artifact_store.put_immutable(record, "slow-draft", 1, "planning", "1.0")
    ref = artifact_ref("slow-draft", 1, digest)
    monkeypatch.setattr(host, "_verify_structural_gap", lambda *args: None)

    second_check_entered = Event()
    continue_scan = Event()
    real_predicate = planning._dependency_exists

    def gated_membership(dependency, available):
        if dependency == "absent":
            second_check_entered.set()
            if not continue_scan.wait(10):
                raise RuntimeError("test did not release comparison")
        return real_predicate(dependency, available)

    monkeypatch.setattr(planning, "_dependency_exists", gated_membership)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            host.scan_planning_candidate,
            record.task_id,
            record.run_id,
            ref,
            "repo",
            ("dependency_readiness",),
            None,
            None,
        )
        try:
            assert second_check_entered.wait(8)
            interim = host.event_store.list(record.task_id)
            # The detector cannot have returned: its second membership comparison is blocked.
            assert sum(event["event_type"] == "scanner_check" for event in interim) >= 2
            assert not any(event["event_type"] == "scanner_completed" for event in interim)
        finally:
            continue_scan.set()
        result = future.result(timeout=10)
    assert result.outcome is ScannerOutcome.BLOCKED
    assert host.event_store.list(record.task_id)[-1]["event_type"] == "scanner_completed"


def test_graph_uniqueness_cycle_and_unknown_evidence_are_independent(tmp_path):
    from pydantic import BaseModel

    from agent.contracts.scanner import CriterionResult, CriterionValidity
    from agent.runtime.scanner_gateway import ScannerGateway

    class Graph(BaseModel):
        actions: list[dict[str, object]]

    cases = (
        ("self", [("a", ("a",))], "cyclic-dependency:graph", "dependency_acyclic"),
        ("cycle", [("a", ("b",)), ("b", ("a",))], "cyclic-dependency:graph", "dependency_acyclic"),
        ("duplicate", [("a", ()), ("a", ())], "duplicate-action:a", "dependency_unique_ids"),
    )
    gateway = ScannerGateway(HostController(tmp_path).artifact_store)
    for label, graph, finding_id, check_id in cases:
        digest = gateway._artifact_store.put_immutable(
            Graph(actions=[{"action_id": action, "depends_on": list(deps)} for action, deps in graph]),
            label,
            1,
            "planning",
            "1.0",
        )
        scan = gateway.scan_exact(artifact_ref(label, 1, digest), "repo", ("dependency_readiness",))
        assert scan.outcome is ScannerOutcome.BLOCKED
        assert finding_id in {finding.finding_id for finding in scan.findings}
        assert any(
            step.check_id == check_id
            and step.criterion_result is CriterionResult.NOT_SATISFIED
            and step.criterion_validity is CriterionValidity.NOT_VALID
            for step in scan.trace_steps
        )


def test_event_persistence_failure_blocks_scan_and_listener_failure_does_not(tmp_path, monkeypatch):
    from agent.runtime.scanner_gateway import ScannerGatewayError

    host = HostController(tmp_path)
    record = make_planning_record()
    digest = host.artifact_store.put_immutable(record, "event-draft", 1, "planning", "1.0")
    ref = artifact_ref("event-draft", 1, digest)
    monkeypatch.setattr(host, "_verify_structural_gap", lambda *args: None)

    # Optional output observers have no authority to change a verified scan.
    result = host.scan_planning_candidate(
        record.task_id,
        record.run_id,
        ref,
        "repo",
        ("dependency_readiness",),
        None,
        None,
        on_event=lambda event: (_ for _ in ()).throw(OSError("observer disconnected")),
    )
    assert host.artifact_store.get_verified(result.request_id, 1)
    assert host.event_store.list(record.task_id)[-1]["event_type"] == "scanner_completed"

    original_append = host.event_store.append

    def failure(task_id, event_type, event_data):
        if event_type == "scanner_check":
            raise OSError("durable event store unavailable")
        return original_append(task_id, event_type, event_data)

    monkeypatch.setattr(host.event_store, "append", failure)
    with pytest.raises(ScannerGatewayError):
        host.scan_planning_candidate(record.task_id, record.run_id, ref, "repo", ("dependency_readiness",), None, None)
    events = host.event_store.list(record.task_id)
    assert events[-1]["event_type"] == "scanner_interrupted"
    assert not any(event["event_type"] == "scanner_completed" for event in events[-2:])


def test_unexecuted_supported_capability_is_not_marked_checked(tmp_path):
    from pydantic import BaseModel

    from agent.runtime.scanner_gateway import ScannerGateway

    class Graph(BaseModel):
        actions: list[dict[str, object]]

    host = HostController(tmp_path)
    digest = host.artifact_store.put_immutable(
        Graph(actions=[{"action_id": "a", "depends_on": []}]), "mixed-cap", 1, "planning", "1.0"
    )
    gateway = ScannerGateway(host.artifact_store)
    gateway.register_detector("syntax", lambda _: ())
    result = gateway.scan_exact(artifact_ref("mixed-cap", 1, digest), "repo", ("syntax", "not_registered"))
    assert result.outcome is ScannerOutcome.BLOCKED
    assert result.capabilities_checked == ()
    assert result.capabilities_not_checked == ("syntax", "not_registered")


def test_event_store_cursor_pages_are_contiguous_and_bounded(tmp_path):
    host = HostController(tmp_path)
    for index in range(275):
        host.event_store.append("paged-task", "scanner_check", f"check-{index}")
    first = host.event_store.list("paged-task", after=0, limit=256)
    second = host.event_store.list("paged-task", after=first[-1]["seq"], limit=256)
    assert len(first) == 256
    assert len(second) == 19
    assert [event["seq"] for event in first + second] == list(range(1, 276))
    assert host.event_store.list("paged-task", after=second[-1]["seq"], limit=256) == []

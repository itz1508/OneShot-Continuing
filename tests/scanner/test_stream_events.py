"""Live Scanner event projection and single-Host Runtime invocation tests."""

from __future__ import annotations

import json

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

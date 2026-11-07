"""HTTP, SSE replay and CLI all consume the existing HostController Scanner."""

from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from agent.cli import cmd_scan
from agent.contracts.host import ReceiptRef
from agent.contracts.scanner import ScannerRunInput
from agent.runtime.controller import HostController
from mvp.service import MVPService
from tests.scanner.test_decision_trace import artifact_ref, make_planning_record


def prepared_scanner(tmp_path):
    service = MVPService(tmp_path)
    task = service.create("Inspect exact Planning evidence")
    task_id, run_id = task["task_id"], task["run_id"]
    checkpoint = service.host.checkpoint_store.load_checkpoint(task_id)
    assert checkpoint is not None
    revision, state, _ = checkpoint
    # Isolate the API/CLI adapter; the complete upstream Planning workflow is not supplied here.
    state["current_stage"] = "planning"
    service.host.checkpoint_store.checkpoint_cas(task_id, revision, state)
    record = make_planning_record().model_copy(update={"task_id": task_id, "run_id": run_id})
    digest = service.artifacts.put_immutable(record, "candidate:" + task_id, 1, "planning", "1.0")
    request = ScannerRunInput(
        run_id=run_id,
        candidate_ref=artifact_ref("candidate:" + task_id, 1, digest),
        repository_identity="repo",
        capabilities=("dependency_readiness",),
        gap_result_ref=artifact_ref("missing-gap", 1, "c" * 64, "structural_analysis_result"),
        gap_receipt_ref=ReceiptRef(receipt_id="missing-receipt", receipt_digest="d" * 64, issuer_id="host"),
    )
    return service, task_id, request


def test_scanner_http_requires_host_receipt_and_operator_permission(tmp_path, monkeypatch):
    import mvp.api

    service, task_id, request = prepared_scanner(tmp_path)
    monkeypatch.setattr(mvp.api, "service", service)
    monkeypatch.setenv("ONESHOT_OPERATOR_TOKEN", "token-expected")
    client = TestClient(mvp.api.app)
    endpoint = f"/api/tasks/{task_id}/scanner"
    payload = request.model_dump(mode="json")
    assert client.post(endpoint, json=payload).status_code == 403
    denied = client.post(endpoint, json=payload, headers={"X-Operator-Token": "token-expected"})
    assert denied.status_code == 409
    assert "host evidence" in denied.json()["detail"]
    assert not [e for e in service.events(task_id) if e["type"].startswith("scanner_")]


def test_real_http_host_scan_sse_replay_and_cli_share_one_event_store(tmp_path, monkeypatch, capsys):
    import mvp.api

    service, task_id, request = prepared_scanner(tmp_path)
    monkeypatch.setattr(mvp.api, "service", service)
    monkeypatch.delenv("ONESHOT_OPERATOR_TOKEN", raising=False)
    # Substitute only upstream structural-gap receipt, not Scanner checks or EventStore.
    monkeypatch.setattr(HostController, "_verify_structural_gap", lambda *args: None)
    client = TestClient(mvp.api.app)
    initial = service.events(task_id)
    cursor = initial[-1]["sequence"]
    endpoint = f"/api/tasks/{task_id}/scanner"
    response = client.post(endpoint, json=request.model_dump(mode="json"))
    assert response.status_code == 200
    scan = response.json()
    assert scan["outcome"] == "blocked"
    replay = client.get(f"/api/tasks/{task_id}/events?after={cursor}").json()
    assert replay[0]["type"] == "scanner_started"
    assert replay[-1]["type"] == "scanner_completed"
    assert any(e["type"] == "scanner_check" and e["detail"]["criterion_result"] == "not_satisfied" for e in replay)
    assert replay[-1]["detail"]["result_ref"]["artifact_id"] == scan["request_id"]
    assert all(isinstance(e["sequence"], int) for e in replay)

    original_events = service.events
    calls = 0

    def finite_sse(tid, after=0):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise sqlite3.OperationalError("a private DB error")
        return original_events(tid, after)

    monkeypatch.setattr(service, "events", finite_sse)
    response = client.get(f"/api/tasks/{task_id}/stream?after={cursor}")
    assert response.status_code == 200
    assert "event: activity" in response.text
    assert '"type": "scanner_check"' in response.text
    assert "event: stream_error" in response.text
    assert "a private DB error" not in response.text
    monkeypatch.setattr(service, "events", original_events)

    path = tmp_path / "scan-request.json"
    path.write_text(request.model_dump_json())
    # No alternate scanner is launched: CLI creates a service over the identical state root.
    code = cmd_scan(task_id, str(path), str(tmp_path))
    assert code == 2  # Actual finding, not an execution error.
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["type"] == "scanner_started"
    assert lines[-2]["type"] == "scanner_completed"
    assert lines[-1]["type"] == "scanner_result"
    assert lines[-1]["result"]["outcome"] == "blocked"
    assert lines[-2]["detail"]["result_ref"]["artifact_id"] == lines[-1]["result"]["request_id"]
    after = service.events(task_id, replay[-1]["sequence"])
    assert after[0]["type"] == "scanner_started"
    assert after[-1]["type"] == "scanner_completed"


def test_scanner_api_rejects_cross_run_and_non_planning_stage(tmp_path, monkeypatch):
    import mvp.api

    service, task_id, request = prepared_scanner(tmp_path)
    monkeypatch.setattr(mvp.api, "service", service)
    monkeypatch.delenv("ONESHOT_OPERATOR_TOKEN", raising=False)
    client = TestClient(mvp.api.app)
    endpoint = f"/api/tasks/{task_id}/scanner"
    wrong_run = request.model_copy(update={"run_id": "different-run"})
    response = client.post(endpoint, json=wrong_run.model_dump(mode="json"))
    assert response.status_code == 400
    assert "run mismatch" in response.json()["detail"]

    checkpoint = service.host.checkpoint_store.load_checkpoint(task_id)
    assert checkpoint is not None
    revision, state, _ = checkpoint
    state["current_stage"] = "research"
    service.host.checkpoint_store.checkpoint_cas(task_id, revision, state)
    response = client.post(endpoint, json=request.model_dump(mode="json"))
    assert response.status_code == 400
    assert "Planning stage" in response.json()["detail"]
    assert not [e for e in service.events(task_id) if e["type"].startswith("scanner_")]


def test_cli_module_command_dispatches_the_same_host_scan(tmp_path, monkeypatch, capsys):
    from agent.cli import main

    service, task_id, request = prepared_scanner(tmp_path)
    monkeypatch.setattr(HostController, "_verify_structural_gap", lambda *args: None)
    request_file = tmp_path / "scan-request.json"
    request_file.write_text(request.model_dump_json())
    monkeypatch.setattr(
        "sys.argv",
        ["agent", "scan", task_id, str(request_file), "--state-root", str(tmp_path)],
    )

    assert main() == 2
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0]["type"] == "scanner_started"
    assert output[-1]["type"] == "scanner_result"
    assert output[-1]["result"]["request_id"] == output[-2]["detail"]["scan_id"]
    assert service.events(task_id)[-1]["type"] == "scanner_completed"



def test_real_host_structural_gap_receipt_allows_http_scanner_without_stub(tmp_path, monkeypatch):
    import mvp.api
    from tests.fixtures.structural_gap import build_gap_inputs

    service, task_id, scan_input = prepared_scanner(tmp_path)
    request, runner = build_gap_inputs(service.host, task_id, scan_input.run_id)
    # The GapAnalyzer runs real fixture backtests and issues a real host receipt
    # for the same exact Planning candidate, rather than bypassing the gate.
    request = request.model_copy(update={"candidate_specification_ref": scan_input.candidate_ref})
    outcome = service.host.run_structural_gap_analysis(request, walking_skeleton_runner=runner)
    assert outcome.completion_receipt_ref is not None
    exact = scan_input.model_copy(
        update={"gap_result_ref": outcome.result_ref, "gap_receipt_ref": outcome.completion_receipt_ref}
    )
    monkeypatch.setattr(mvp.api, "service", service)
    monkeypatch.delenv("ONESHOT_OPERATOR_TOKEN", raising=False)
    response = TestClient(mvp.api.app).post(
        f"/api/tasks/{task_id}/scanner", json=exact.model_dump(mode="json")
    )
    assert response.status_code == 200
    scan = response.json()
    assert scan["outcome"] == "blocked"
    assert scan["findings"] and scan["request_id"].startswith("scanner-")
    assert service.events(task_id)[-1]["type"] == "scanner_completed"


def test_duplicate_requested_capability_is_rejected(tmp_path, monkeypatch):
    import mvp.api

    service, task_id, request = prepared_scanner(tmp_path)
    monkeypatch.setattr(mvp.api, "service", service)
    payload = request.model_dump(mode="json")
    payload["capabilities"] = ["dependency_readiness", "dependency_readiness"]
    response = TestClient(mvp.api.app).post(f"/api/tasks/{task_id}/scanner", json=payload)
    assert response.status_code == 422
    assert not [e for e in service.events(task_id) if e["type"].startswith("scanner_")]

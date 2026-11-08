"""Synthetic pinned Scanner checks for host gate tests only."""

from agent.contracts.scanner import ScannerEvidence
from agent.contracts.tool_registry import SandboxProfile, ToolEffect, ToolInvocation, ToolRegistrySnapshot, ToolSpec
from agent.runtime.controller import HostController
from agent.runtime.host_gap_analyzer import StructuralGapOutcome
from agent.runtime.scanner_check_registry import (
    ScannerCheck,
    ScannerCheckRegistrySnapshot,
    pin_scanner_check_registry,
)
from agent.runtime.scanner_evidence import persist_scan_result
from agent.runtime.tool_registry import pin_tool_registry


def passing_scan(controller: HostController, gap: StructuralGapOutcome) -> ScannerEvidence:
    """Pass a synthetic check; its digests are fixtures, not runnable identities."""
    tool_ref = pin_tool_registry(
        controller.artifact_store,
        ToolRegistrySnapshot(
            registry_version="synthetic-test",
            tools=(
                ToolSpec(
                    tool_id="scanner-syntax",
                    version="test",
                    executable_digest="a" * 64,
                    argv_template=("test-scanner",),
                    allowed_stages=("planning",),
                    effect=ToolEffect.READ_ONLY,
                    timeout_seconds=10,
                    max_output_bytes=1024,
                    sandbox_profile_id="test-profile",
                ),
            ),
            sandbox_profiles=(SandboxProfile(profile_id="test-profile", image_ref="test@sha256:" + "b" * 64),),
        ),
        "synthetic-scanner-tools",
    )
    check_ref = pin_scanner_check_registry(
        controller.artifact_store,
        ScannerCheckRegistrySnapshot(
            tool_registry_ref=tool_ref,
            checks=(
                ScannerCheck(capability="syntax", invocation=ToolInvocation(tool_id="scanner-syntax")),
                ScannerCheck(capability="types", invocation=ToolInvocation(tool_id="scanner-syntax")),
            ),
        ),
        "synthetic-scanner-checks",
    )
    controller.configure_scanner_checks(check_ref)
    controller.scanner.register_detector("syntax", lambda _: ())
    controller.scanner.register_detector("types", lambda _: ())
    assert gap.completion_receipt_ref is not None
    outcome = controller.scan_planning_candidate(
        gap.result.task_id,
        gap.result.run_id,
        gap.result.candidate_specification_ref,
        "repo-001",
        ("syntax", "types"),
        gap.result_ref,
        gap.completion_receipt_ref,
    )
    assert controller.scanner_checks is not None
    persisted = persist_scan_result(
        controller.artifact_store,
        controller.receipt_store,
        outcome,
        controller.scanner_checks,
    )
    assert persisted.evidence is not None
    return persisted.evidence

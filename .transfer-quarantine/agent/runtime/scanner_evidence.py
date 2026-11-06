"""Host-owned Scanner result persistence and approval-readiness verification."""

from __future__ import annotations

from dataclasses import dataclass

from agent.contracts.common import ArtifactRef
from agent.contracts.host import ReceiptRef
from agent.contracts.planning_coverage import planning_coverage
from agent.contracts.scanner import ScannerEvidence, ScannerOutcome, ScannerResult
from agent.contracts.validation.structural import CONCERNS
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.canonical_serialization import SERIALIZER_PROFILE, canonical_bytes, digest_raw
from agent.runtime.receipt_store import ReceiptStore
from agent.runtime.scanner_check_registry import ScannerCheckRegistry


@dataclass(frozen=True)
class ScannerScanOutcome:
    result: ScannerResult
    result_ref: ArtifactRef
    evidence: ScannerEvidence | None


def scanner_receipt_subject(result: ScannerResult, result_digest: str) -> str:
    if result.candidate_ref is None or result.registry_ref is None:
        raise ValueError("Scanner result is not bound to candidate and registry")
    return (
        f"scanner-pass:{result.task_id}:{result.run_id}:"
        f"{result.candidate_ref.artifact_id}:{result.candidate_ref.artifact_revision}:"
        f"{result.candidate_ref.artifact_digest}:{result.registry_ref.artifact_digest}:{result_digest}"
    )


def persist_scan_result(
    artifacts: ArtifactStore,
    receipts: ReceiptStore,
    result: ScannerResult,
    registry: ScannerCheckRegistry,
) -> ScannerScanOutcome:
    if result.registry_ref != registry.ref or result.candidate_ref is None:
        raise ValueError("Scanner result has no matching verified registry or candidate")
    result_id = (
        f"scanner-result:{result.task_id}:{result.run_id}:"
        f"{result.candidate_ref.artifact_id}:{result.candidate_ref.artifact_revision}:"
        f"{registry.ref.artifact_digest}:{digest_raw(canonical_bytes(result))[:16]}"
    )
    digest = artifacts.put_immutable(result, result_id, 1, "scanner_result", "1.0")
    result_ref = ArtifactRef(
        artifact_id=result_id,
        artifact_revision=1,
        artifact_digest=digest,
        contract_id="scanner_result",
        contract_version="1.0",
        serializer_profile=SERIALIZER_PROFILE,
    )
    complete = (
        result.outcome is ScannerOutcome.PASS
        and not result.findings
        and not result.capabilities_not_checked
        and result.requested_capabilities == registry.required_capabilities
        and result.capabilities_checked == registry.required_capabilities
        and bool(result.repository_identity)
        and result.planning_coverage is not None
        and result.planning_coverage
        == planning_coverage(structural_concerns=CONCERNS, scanner_capabilities=result.capabilities_checked)
        and not result.planning_coverage.uncovered_categories
        and not result.planning_coverage.unmapped_scanner_capabilities
    )
    if not complete:
        return ScannerScanOutcome(result=result, result_ref=result_ref, evidence=None)
    receipt_id = f"scanner-pass:{result_id}"
    _, receipt_digest = receipts.issue_verified(receipt_id, "host", scanner_receipt_subject(result, digest))
    evidence = ScannerEvidence(
        result_ref=result_ref,
        receipt_ref=ReceiptRef(receipt_id=receipt_id, receipt_digest=receipt_digest, issuer_id="host"),
    )
    return ScannerScanOutcome(result=result, result_ref=result_ref, evidence=evidence)


def verify_scanner_evidence(
    artifacts: ArtifactStore,
    receipts: ReceiptStore,
    evidence: ScannerEvidence,
    candidate_ref: ArtifactRef,
    registry: ScannerCheckRegistry,
    task_id: str,
    run_id: str,
    repository_identity: str | None = None,
) -> ScannerResult:
    ref = evidence.result_ref
    if ref.contract_id != "scanner_result" or ref.contract_version != "1.0":
        raise ValueError("wrong Scanner result contract")
    raw = artifacts.get_verified(ref.artifact_id, ref.artifact_revision)
    if digest_raw(raw) != ref.artifact_digest:
        raise ValueError("Scanner result digest mismatch")
    result = ScannerResult.model_validate_json(raw)
    if (
        result.task_id != task_id
        or result.run_id != run_id
        or result.candidate_ref != candidate_ref
        or result.registry_ref != registry.ref
        or not result.repository_identity
        or (repository_identity is not None and result.repository_identity != repository_identity)
        or result.outcome is not ScannerOutcome.PASS
        or bool(result.findings)
        or bool(result.capabilities_not_checked)
        or result.requested_capabilities != registry.required_capabilities
        or result.capabilities_checked != registry.required_capabilities
        or result.planning_coverage is None
        or result.planning_coverage
        != planning_coverage(structural_concerns=CONCERNS, scanner_capabilities=result.capabilities_checked)
        or bool(result.planning_coverage.uncovered_categories)
        or bool(result.planning_coverage.unmapped_scanner_capabilities)
    ):
        raise ValueError("Scanner coverage or identity is not complete")
    subject = scanner_receipt_subject(result, ref.artifact_digest)
    if evidence.receipt_ref.issuer_id != "host" or not receipts.verify(
        evidence.receipt_ref.receipt_id, evidence.receipt_ref.receipt_digest, subject
    ):
        raise ValueError("Scanner pass receipt is not verified")
    return result

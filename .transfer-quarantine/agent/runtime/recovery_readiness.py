"""Verified host evidence required before executable Build admission."""

from __future__ import annotations

from pydantic import Field, model_validator

from agent.contracts.common import ArtifactRef, ContractModel, DiagnosticStatus
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.canonical_serialization import SERIALIZER_PROFILE, digest_raw


class RecoveryReadiness(ContractModel):
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    checkpoint_ref: ArtifactRef
    operation_ledger_ref: ArtifactRef
    reconciliation_check_ref: ArtifactRef
    diagnostic_status: DiagnosticStatus

    @model_validator(mode="after")
    def require_valid_evidence(self) -> RecoveryReadiness:
        if self.diagnostic_status is not DiagnosticStatus.VALID:
            raise ValueError("recovery readiness is not valid")
        return self


def pin_recovery_readiness(artifacts: ArtifactStore, record: RecoveryReadiness, artifact_id: str) -> ArtifactRef:
    for ref in (record.checkpoint_ref, record.operation_ledger_ref, record.reconciliation_check_ref):
        if artifacts.get_digest(ref.artifact_id, ref.artifact_revision) != ref.artifact_digest:
            raise ValueError("recovery readiness evidence is missing or stale")
        artifacts.get_verified(ref.artifact_id, ref.artifact_revision)
    digest = artifacts.put_immutable(record, artifact_id, 1, "recovery_readiness", "1.0")
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_revision=1,
        artifact_digest=digest,
        contract_id="recovery_readiness",
        contract_version="1.0",
        serializer_profile=SERIALIZER_PROFILE,
    )


def verify_recovery_readiness(artifacts: ArtifactStore, ref: ArtifactRef) -> RecoveryReadiness:
    if ref.contract_id != "recovery_readiness" or ref.contract_version != "1.0":
        raise ValueError("wrong recovery readiness contract")
    raw = artifacts.get_verified(ref.artifact_id, ref.artifact_revision)
    if digest_raw(raw) != ref.artifact_digest:
        raise ValueError("recovery readiness digest mismatch")
    record = RecoveryReadiness.model_validate_json(raw)
    for evidence in (record.checkpoint_ref, record.operation_ledger_ref, record.reconciliation_check_ref):
        if artifacts.get_digest(evidence.artifact_id, evidence.artifact_revision) != evidence.artifact_digest:
            raise ValueError("recovery readiness evidence changed")
        artifacts.get_verified(evidence.artifact_id, evidence.artifact_revision)
    return record

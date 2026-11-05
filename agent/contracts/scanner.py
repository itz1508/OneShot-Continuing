"""Scanner capability request and finding shapes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from agent.contracts.common import ArtifactRef, ContractModel, Sha256
from agent.contracts.host import ReceiptRef
from agent.contracts.planning_coverage import PlanningCoverage


class ScannerOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"


class ScannerCapabilityID(StrEnum):
    SYNTAX = "syntax"
    IMPORTS = "imports"
    TYPES = "types"
    SECURITY = "security"
    PATHS = "paths"
    COVERAGE = "coverage"


class ScannerRequest(ContractModel):
    task_id: str = Field(min_length=1)
    candidate_artifact: ArtifactRef
    specification_revision: int = Field(ge=1)
    specification_digest: Sha256
    repository_source: str = Field(min_length=1)
    requested_capabilities: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_candidate_binding(self) -> ScannerRequest:
        if (
            self.candidate_artifact.artifact_revision != self.specification_revision
            or self.candidate_artifact.artifact_digest != self.specification_digest
        ):
            raise ValueError("Scanner request does not bind the exact candidate")
        if len(set(self.requested_capabilities)) != len(self.requested_capabilities):
            raise ValueError("duplicate Scanner capability")
        return self


class ScannerFinding(ContractModel):
    finding_id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    message: str = Field(min_length=1)
    location: str = ""
    evidence_ref: str = ""


class ScannerResult(ContractModel):
    request_id: str = Field(min_length=1)
    task_id: str = ""
    run_id: str = ""
    outcome: ScannerOutcome
    capabilities_checked: tuple[str, ...] = ()
    capabilities_not_checked: tuple[str, ...] = ()
    findings: tuple[ScannerFinding, ...] = ()
    findings_artifact_id: str | None = None
    findings_artifact_digest: Sha256 | None = None
    limitation_reasons: tuple[str, ...] = ()
    candidate_ref: ArtifactRef | None = None
    repository_identity: str = ""
    requested_capabilities: tuple[str, ...] = ()
    registry_ref: ArtifactRef | None = None
    planning_coverage: PlanningCoverage | None = None


class ScannerEvidence(ContractModel):
    """Host-persisted scan result and trusted receipt for an exact candidate."""

    result_ref: ArtifactRef
    receipt_ref: ReceiptRef

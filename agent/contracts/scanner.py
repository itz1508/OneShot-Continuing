"""Scanner capability request and finding shapes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from agent.contracts.common import ArtifactRef, ContractModel, Sha256


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


class ScannerFinding(ContractModel):
    finding_id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    message: str = Field(min_length=1)
    location: str = ""
    evidence_ref: str = ""



class ObservationState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class CriterionResult(StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    UNKNOWN = "unknown"


class CriterionValidity(StrEnum):
    VALID = "valid"
    NOT_VALID = "not_valid"


class ScannerTraceStep(ContractModel):
    """An executed comparison; criterion and execution outcomes are distinct."""

    check_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    scanner_version: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    observation_state: ObservationState
    observed_value: bool | int | float | str | None
    operator: str = Field(min_length=1)
    expected_value: bool | int | float | str | None
    threshold: float | None = None
    criterion_result: CriterionResult
    criterion_validity: CriterionValidity
    required: bool = True
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""

    @model_validator(mode="after")
    def verify_comparison(self) -> ScannerTraceStep:
        if self.observation_state is ObservationState.UNKNOWN:
            if self.observed_value is not None or self.criterion_result is not CriterionResult.UNKNOWN:
                raise ValueError("unknown observations must have null values and unknown results")
        elif self.criterion_result is CriterionResult.UNKNOWN or self.observed_value is None:
            raise ValueError("known observations require a value and a comparison result")
        if self.criterion_validity is CriterionValidity.VALID and (
            self.criterion_result is not CriterionResult.SATISFIED or not self.evidence_refs
        ):
            raise ValueError("valid checklist criteria require satisfaction and evidence")
        if self.required and self.criterion_result is CriterionResult.UNKNOWN:
            if self.criterion_validity is not CriterionValidity.NOT_VALID:
                raise ValueError("unknown required criteria cannot be valid")
        return self


class ScannerEvidenceRequest(ContractModel):
    check_id: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    missing_evidence: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class TracedDetectorResult(ContractModel):
    findings: tuple[ScannerFinding, ...] = ()
    trace_steps: tuple[ScannerTraceStep, ...] = ()
    evidence_requests: tuple[ScannerEvidenceRequest, ...] = ()
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)
    parse_duration_ns: int = Field(default=0, ge=0)


class ScannerResult(ContractModel):
    request_id: str = Field(min_length=1)
    outcome: ScannerOutcome
    capabilities_checked: tuple[str, ...] = ()
    capabilities_not_checked: tuple[str, ...] = ()
    findings: tuple[ScannerFinding, ...] = ()
    findings_artifact_id: str | None = None
    findings_artifact_digest: Sha256 | None = None
    limitation_reasons: tuple[str, ...] = ()
    candidate_ref: ArtifactRef | None = None
    trace_steps: tuple[ScannerTraceStep, ...] = ()
    evidence_requests: tuple[ScannerEvidenceRequest, ...] = ()
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)
    parse_duration_ns: int = Field(default=0, ge=0)

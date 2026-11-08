"""Build Validation stage contract — independent E2E verification."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from agent.contracts.common import ArtifactRef, ContractModel, DiagnosticStatus, StepResult
from agent.contracts.planning import IssueType


class CriterionResult(StrEnum):
    """Independent observation validity, not a probability of Build success."""

    VALID = "valid"
    NOT_VALID = "not_valid"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"


class ValidationIssueInput(ContractModel):
    """Categorized Planning input for a non-valid verification observation."""

    issue_type: IssueType
    reason: str = Field(min_length=1)
    evidence_status: DiagnosticStatus


class ObservedCriterionResult(ContractModel):
    criterion_id: str = Field(min_length=1)
    observed_result: str = Field(min_length=1)
    outcome: CriterionResult = CriterionResult.NOT_RUN
    evidence_refs: tuple[str, ...] = ()
    independent_observation: str = Field(min_length=1)
    issue_input: ValidationIssueInput | None = None

    @model_validator(mode="after")
    def classify_evidence(self) -> ObservedCriterionResult:
        if self.outcome is CriterionResult.VALID:
            if not self.evidence_refs or self.issue_input is not None:
                raise ValueError("valid criterion requires evidence and no Planning issue")
        elif self.issue_input is None:
            raise ValueError("non-valid criterion requires categorized Planning input")
        return self


class E2EResult(ContractModel):
    e2e_id: str = Field(min_length=1)
    entrypoint: str = Field(min_length=1)
    exit_code: int
    stdout_digest: str = ""
    stderr_digest: str = ""
    duration_ms: int = 0
    outcome: CriterionResult = CriterionResult.NOT_RUN
    evidence_refs: tuple[str, ...] = ()
    issue_input: ValidationIssueInput | None = None

    @model_validator(mode="after")
    def classify_evidence(self) -> E2EResult:
        if self.outcome is CriterionResult.VALID:
            if not self.evidence_refs or self.exit_code != 0 or self.issue_input is not None:
                raise ValueError("valid E2E check requires evidence, zero exit and no Planning issue")
        elif self.issue_input is None:
            raise ValueError("non-valid E2E check requires categorized Planning input")
        return self


class BuildValidationInput(ContractModel):
    build_record_ref: ArtifactRef
    build_receipt_ref: str = Field(min_length=1)


class BuildValidationRecord(ContractModel):
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage_revision: int = Field(ge=1)
    build_ref: ArtifactRef
    criterion_results: tuple[ObservedCriterionResult, ...] = ()
    e2e_results: tuple[E2EResult, ...] = ()
    step_results: tuple[StepResult, ...] = ()

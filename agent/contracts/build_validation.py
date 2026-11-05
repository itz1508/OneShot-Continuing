"""Independent E2E verification evidence within the Build stage."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from agent.contracts.common import ArtifactRef, ContractModel, DiagnosticStatus, StepResult
from agent.contracts.planning import IssueType


class CriterionResult(StrEnum):
    VALID = "valid"
    NOT_VALID = "not_valid"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"


class ValidationIssueInput(ContractModel):
    """A verifier observation for the next Planning revision, not a PlanningIssue."""

    issue_type: IssueType
    reason: str = Field(min_length=1)
    evidence_status: DiagnosticStatus


class ValidationIssueSource(ContractModel):
    check_id: str = Field(min_length=1)
    outcome: CriterionResult
    issue: ValidationIssueInput
    evidence_refs: tuple[str, ...] = ()


class ObservedCriterionResult(ContractModel):
    criterion_id: str = Field(min_length=1)
    observed_result: str = Field(min_length=1)
    outcome: CriterionResult = CriterionResult.NOT_RUN
    evidence_refs: tuple[str, ...] = ()
    independent_observation: str = Field(min_length=1)
    issue_input: ValidationIssueInput | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> ObservedCriterionResult:
        if self.outcome is CriterionResult.VALID:
            if not self.evidence_refs or self.issue_input is not None:
                raise ValueError("valid criterion requires evidence and no issue input")
        elif self.issue_input is None:
            raise ValueError("criterion without valid outcome requires a categorized Planning input")
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
    def validate_outcome(self) -> E2EResult:
        if self.outcome is CriterionResult.VALID:
            if self.exit_code != 0 or not self.evidence_refs or self.issue_input is not None:
                raise ValueError("valid E2E check requires zero exit, evidence, and no issue input")
        elif self.issue_input is None:
            raise ValueError("E2E check without valid outcome requires a categorized Planning input")
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

    def planning_issue_inputs(self) -> tuple[ValidationIssueSource, ...]:
        """Expose verifier findings for host routing without creating Planning issues."""
        issues: list[ValidationIssueSource] = []
        for item in self.criterion_results:
            if item.issue_input is not None:
                issues.append(
                    ValidationIssueSource(
                        check_id=item.criterion_id,
                        outcome=item.outcome,
                        issue=item.issue_input,
                        evidence_refs=item.evidence_refs,
                    )
                )
        for e2e in self.e2e_results:
            if e2e.issue_input is not None:
                issues.append(
                    ValidationIssueSource(
                        check_id=e2e.e2e_id,
                        outcome=e2e.outcome,
                        issue=e2e.issue_input,
                        evidence_refs=e2e.evidence_refs,
                    )
                )
        return tuple(issues)


class PlanningReworkInput(ContractModel):
    """Host-routed verifier findings; only the Planner may create PlanningIssue."""

    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    planning_revision: int = Field(ge=2)
    validation_ref: ArtifactRef
    issue_sources: tuple[ValidationIssueSource, ...] = Field(min_length=1)

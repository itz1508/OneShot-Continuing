"""Independent check outcomes and Planning issue causes remain separate."""

import pytest
from pydantic import ValidationError

from agent.contracts.build_validation import (
    CriterionResult,
    E2EResult,
    ObservedCriterionResult,
    ValidationIssueInput,
)
from agent.contracts.common import DiagnosticStatus

ISSUE_TYPES = (
    "compatibility",
    "dependency",
    "interface",
    "concurrency",
    "security",
    "recovery",
    "buildability",
    "verifiability",
)


@pytest.mark.parametrize("issue_type", ISSUE_TYPES)
def test_all_planning_issue_categories_can_describe_not_valid_validation(issue_type):
    issue = ValidationIssueInput(
        issue_type=issue_type, reason="observed failure", evidence_status=DiagnosticStatus.NOT_VALID
    )
    result = ObservedCriterionResult(
        criterion_id="AC-001",
        observed_result="not valid",
        outcome=CriterionResult.NOT_VALID,
        independent_observation="verifier observed failure",
        issue_input=issue,
    )
    assert result.outcome is CriterionResult.NOT_VALID
    assert result.issue_input.issue_type == issue_type


@pytest.mark.parametrize("outcome", (CriterionResult.NOT_VALID, CriterionResult.BLOCKED, CriterionResult.NOT_RUN))
def test_checks_without_valid_outcome_need_categorized_planning_input(outcome):
    with pytest.raises(ValidationError, match="categorized Planning input"):
        E2EResult(e2e_id="check", entrypoint="app", exit_code=1, outcome=outcome)
    issue = ValidationIssueInput(
        issue_type="verifiability", reason="check unavailable", evidence_status=DiagnosticStatus.UNCERTAINTY
    )
    result = E2EResult(e2e_id="check", entrypoint="app", exit_code=1, outcome=outcome, issue_input=issue)
    assert result.outcome is outcome


def test_valid_requires_evidence_and_never_carries_an_issue():
    with pytest.raises(ValidationError, match="valid E2E check requires"):
        E2EResult(e2e_id="check", entrypoint="app", exit_code=0, outcome=CriterionResult.VALID)
    valid = E2EResult(
        e2e_id="check",
        entrypoint="app",
        exit_code=0,
        outcome=CriterionResult.VALID,
        evidence_refs=("EVD-001",),
    )
    assert valid.issue_input is None


def test_criterion_result_uses_valid_and_not_valid_values():
    assert {item.value for item in CriterionResult} == {"valid", "not_valid", "blocked", "not_run"}
    with pytest.raises(ValueError):
        CriterionResult("pass")
    with pytest.raises(ValueError):
        CriterionResult("fail")

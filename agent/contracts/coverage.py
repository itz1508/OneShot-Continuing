"""Shared Planning coverage result shape, independent of validation module imports."""

from __future__ import annotations

from agent.contracts.common import ContractModel
from agent.contracts.planning import IssueType


class PlanningCoverage(ContractModel):
    """Sources for every category, including categories left uncovered."""

    category_sources: dict[IssueType, tuple[str, ...]]
    uncovered_categories: tuple[IssueType, ...] = ()
    unmapped_scanner_capabilities: tuple[str, ...] = ()

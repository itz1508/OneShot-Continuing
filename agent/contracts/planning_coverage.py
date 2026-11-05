"""One Planning issue taxonomy for structural and Scanner coverage evidence."""

from __future__ import annotations

from agent.contracts.common import ContractModel
from agent.contracts.planning import IssueType
from agent.contracts.validation.structural import CONCERNS

ISSUE_CATEGORIES: tuple[IssueType, ...] = (
    "compatibility",
    "dependency",
    "interface",
    "concurrency",
    "security",
    "recovery",
    "buildability",
    "verifiability",
)

# Each structural concern has one owner; these labels describe what that
# owner's existing check can establish, without dispatching another check.
STRUCTURAL_CATEGORIES: dict[str, tuple[IssueType, ...]] = {
    "identity": ("compatibility",),
    "authority": ("security",),
    "registry": ("dependency",),
    "provenance": ("verifiability",),
    "persistence": ("recovery",),
    "recovery": ("recovery",),
    "concurrency": ("concurrency",),
    "pinning": ("compatibility",),
    "evidence": ("verifiability",),
    "cleanup": ("recovery",),
}

SCANNER_CATEGORIES: dict[str, tuple[IssueType, ...]] = {
    "syntax": ("buildability",),
    "imports": ("dependency",),
    "types": ("interface", "compatibility"),
    "security": ("security",),
    "paths": ("security", "recovery"),
    "coverage": ("verifiability",),
}


class PlanningCoverage(ContractModel):
    """Sources for every category, including categories left uncovered."""

    category_sources: dict[IssueType, tuple[str, ...]]
    uncovered_categories: tuple[IssueType, ...] = ()
    unmapped_scanner_capabilities: tuple[str, ...] = ()


def planning_coverage(
    *, structural_concerns: frozenset[str], scanner_capabilities: tuple[str, ...]
) -> PlanningCoverage:
    """Classify checks already run; never treat a declared check as observed."""
    if set(STRUCTURAL_CATEGORIES) != CONCERNS:
        raise ValueError("structural concern classification is incomplete")
    if not structural_concerns.issubset(CONCERNS):
        raise ValueError("unknown structural concern in Planning coverage")
    sources: dict[IssueType, list[str]] = {category: [] for category in ISSUE_CATEGORIES}
    for concern in sorted(structural_concerns):
        for category in STRUCTURAL_CATEGORIES[concern]:
            sources[category].append(f"structural:{concern}")
    unmapped: list[str] = []
    for capability in scanner_capabilities:
        categories = SCANNER_CATEGORIES.get(capability)
        if categories is None:
            unmapped.append(capability)
            continue
        for category in categories:
            sources[category].append(f"scanner:{capability}")
    return PlanningCoverage(
        category_sources={category: tuple(sources[category]) for category in ISSUE_CATEGORIES},
        uncovered_categories=tuple(category for category in ISSUE_CATEGORIES if not sources[category]),
        unmapped_scanner_capabilities=tuple(unmapped),
    )

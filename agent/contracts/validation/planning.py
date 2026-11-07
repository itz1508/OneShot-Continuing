"""Semantic validators for Planning records."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from time import perf_counter_ns

from agent.contracts.planning import (
    BuildSpecification,
    PlanningRecord,
)
from agent.contracts.scanner import (
    CriterionResult,
    CriterionValidity,
    ObservationState,
    ScannerFinding,
    ScannerTraceStep,
    TracedDetectorResult,
)


def validate_reviews(record: PlanningRecord) -> list[str]:
    """Every code intent must be dispositioned."""
    errors: list[str] = []
    # Intent IDs come from the audit package; we validate reviews exist
    for review in record.intent_reviews:
        if review.disposition.value in ("combine", "split") and not (
            review.resulting_review_ids or review.resulting_decision_ids or review.resulting_action_ids
        ):
            errors.append(f"review {review.review_id} combines/splits without resulting IDs")
    return errors


def validate_planning_issues(record: PlanningRecord) -> list[str]:
    errors: list[str] = []
    for issue in record.issues:
        if issue.issue_type == "security" and not issue.receipt_ref:
            errors.append(f"security issue {issue.issue_id} missing technical check receipt")
    return errors


def validate_decisions(record: PlanningRecord) -> list[str]:
    errors: list[str] = []
    for decision in record.design_decisions:
        if len(decision.options_considered) < 2:
            errors.append(f"decision {decision.decision_id} has fewer than 2 alternatives")
    return errors


def validate_refactors(record: PlanningRecord) -> list[str]:
    errors: list[str] = []
    for refactor in record.corrective_refactors:
        if not refactor.finding_ref:
            errors.append(f"refactor {refactor.refactor_id} has no finding reference")
    return errors


def _dependency_exists(dependency_id: str, action_ids: set[str]) -> bool:
    """Shared observed predicate for legacy validation and emitted traces."""
    return dependency_id in action_ids


def validate_action_graph(spec: BuildSpecification) -> list[str]:
    errors: list[str] = []
    action_ids = [a.action_id for a in spec.actions]
    if len(action_ids) != len(set(action_ids)):
        errors.append("duplicate action IDs")
    id_set = set(action_ids)
    for action in spec.actions:
        for dep in action.depends_on:
            if not _dependency_exists(dep, id_set):
                errors.append(f"action {action.action_id} depends on unknown action {dep}")
    # Check for cycles (simple DFS)
    visited: set[str] = set()
    in_stack: set[str] = set()

    def visit(aid: str) -> bool:
        if aid in in_stack:
            return True
        if aid in visited:
            return False
        visited.add(aid)
        in_stack.add(aid)
        matching = [a for a in spec.actions if a.action_id == aid]
        if not matching:
            in_stack.discard(aid)
            return False
        action = matching[0]
        for dep in action.depends_on:
            if visit(dep):
                return True
        in_stack.discard(aid)
        return False

    for aid in action_ids:
        if visit(aid):
            errors.append(f"cycle detected involving action {aid}")
            break
    return errors


def validate_phase_graph(spec: BuildSpecification) -> list[str]:
    errors: list[str] = []
    action_ids = {a.action_id for a in spec.actions}
    for phase in spec.phases:
        for aid in phase.action_ids:
            if aid not in action_ids:
                errors.append(f"phase {phase.phase_id} references unknown action {aid}")
    return errors


def validate_spec_coverage(spec: BuildSpecification) -> list[str]:
    errors: list[str] = []
    for cov in spec.requirement_coverage:
        if cov.status == "covered" and not cov.specification_refs:
            errors.append(f"requirement {cov.requirement_id} marked covered without specification refs")
    for ccov in spec.criterion_coverage:
        if ccov.status == "covered" and not ccov.validation_step_refs:
            errors.append(f"criterion {ccov.criterion_id} marked covered without validation step refs")
    return errors


def validate_paths(spec: BuildSpecification) -> list[str]:
    errors: list[str] = []
    paths: dict[str, str] = {}
    for action in spec.actions:
        path = getattr(action, "target_path", None) or getattr(action, "source_path", None)
        if path:
            if path in paths and paths[path] != action.action_id:
                errors.append(f"path collision: {path} in actions {paths[path]} and {action.action_id}")
            paths[path] = action.action_id
    return errors


# Bounded pure parsing: no evidence, authorization, timing or traces are cached.
DEPENDENCY_PARSER_VERSION = "1"
DEPENDENCY_RULE_VERSION = "1"
DEPENDENCY_SCANNER_VERSION = "1"
MAX_CACHED_SOURCE_BYTES = 262_144


@lru_cache(maxsize=128)
def parse_action_dependency_facts(parser_version: str, source_bytes: bytes) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Extract immutable action/dependency facts from exact candidate bytes."""
    if not parser_version:
        raise ValueError("parser version required")
    data = json.loads(source_bytes)
    if "candidate" in data:
        data = data["candidate"]
    if "build_spec" in data:
        data = data["build_spec"]
    actions = data["actions"]
    if not isinstance(actions, list):
        raise ValueError("actions must be an array")
    facts: list[tuple[str, tuple[str, ...]]] = []
    for action in actions:
        action_id = action["action_id"]
        dependencies = action.get("depends_on", [])
        if not isinstance(action_id, str) or not action_id:
            raise ValueError("invalid action ID")
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            raise ValueError("invalid dependency list")
        facts.append((action_id, tuple(dependencies)))
    return tuple(facts)


def scan_action_dependencies(
    source_bytes: bytes,
    target_ref: str,
    evidence_ref: str,
    *,
    on_step: Callable[[ScannerTraceStep, ScannerFinding | None], None] | None = None,
) -> TracedDetectorResult:
    """Emit actual dependency membership comparisons, not generated explanations."""
    before = parse_action_dependency_facts.cache_info()
    started = perf_counter_ns()
    # Oversized inputs are analyzed but not retained in the bounded cache.
    if len(source_bytes) <= MAX_CACHED_SOURCE_BYTES:
        facts = parse_action_dependency_facts(DEPENDENCY_PARSER_VERSION, source_bytes)
    else:
        facts = parse_action_dependency_facts.__wrapped__(DEPENDENCY_PARSER_VERSION, source_bytes)
    duration = perf_counter_ns() - started
    after = parse_action_dependency_facts.cache_info()
    known_ids = {action_id for action_id, _ in facts}
    traces: list[ScannerTraceStep] = []
    findings: list[ScannerFinding] = []
    for action_id, dependencies in facts:
        # An empty dependency set is a known, vacuously satisfied observation.
        for dependency in dependencies or ("",):
            observed = not dependency or _dependency_exists(dependency, known_ids)
            traces.append(
                ScannerTraceStep(
                    check_id="dependency_readiness",
                    rule_version=DEPENDENCY_RULE_VERSION,
                    scanner_version=DEPENDENCY_SCANNER_VERSION,
                    target_ref=f"{target_ref}:action:{action_id}",
                    observation_state=ObservationState.KNOWN,
                    observed_value=bool(observed),
                    operator="equals",
                    expected_value=True,
                    criterion_result=CriterionResult.SATISFIED if observed else CriterionResult.NOT_SATISFIED,
                    criterion_validity=CriterionValidity.VALID if observed else CriterionValidity.NOT_VALID,
                    evidence_refs=(evidence_ref,),
                    reason="No dependencies declared" if not dependency else f"Dependency reference: {dependency}",
                )
            )
            if not observed:
                findings.append(
                    ScannerFinding(
                        finding_id=f"missing-dependency:{action_id}:{dependency}",
                        capability="dependency_readiness",
                        severity="error",
                        message=f"Action {action_id} references absent action {dependency}",
                        location=f"action:{action_id}",
                        evidence_ref=evidence_ref,
                    )
                )
            # Publish the actual observed comparison before advancing to the next one.
            if on_step is not None:
                on_step(traces[-1], findings[-1] if not observed else None)
    if not facts:
        raise ValueError("candidate has no actions to validate")
    return TracedDetectorResult(
        findings=tuple(findings),
        trace_steps=tuple(traces),
        cache_hits=after.hits - before.hits,
        cache_misses=after.misses - before.misses,
        parse_duration_ns=duration,
    )

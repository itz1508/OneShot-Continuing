"""Semantic validators for Planning records."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import Literal

from pydantic import Field

from agent.contracts.common import ContractModel
from agent.contracts.planning import (
    BuildAction,
    BuildSpecification,
    CandidateSpecification,
    PlanningRecord,
)
from agent.contracts.scanner import ScannerFinding


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


def validate_action_graph(spec: BuildSpecification) -> list[str]:
    errors: list[str] = []
    action_ids = [a.action_id for a in spec.actions]
    if len(action_ids) != len(set(action_ids)):
        errors.append("duplicate action IDs")
    id_set = set(action_ids)
    for action in spec.actions:
        for dep in action.depends_on:
            if dep not in id_set:
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


class DraftRepair(ContractModel):
    """Explicit Planner-owned repair instruction, never a scanner-side effect."""

    action_id: str = Field(min_length=1)
    kind: Literal["remove_action", "set_dependencies", "restore_source_path"]
    evidence_ref: str = Field(min_length=1)
    dependencies: tuple[str, ...] = ()
    source_path: str = ""


def scan_plan_draft(
    candidate: CandidateSpecification,
    source_files: Mapping[str, str],
    *,
    source_id: str,
    accepted_requirements: tuple[str, ...],
    allowed_paths: tuple[str, ...],
    required_criteria: Mapping[str, tuple[str, ...]] | None = None,
    source_snapshot_complete: bool = False,
) -> tuple[ScannerFinding, ...]:
    """Read-only structural inspection of one draft; source_files are pinned evidence.

    The caller supplies accepted requirements, scope, and source identity from trusted
    upstream artifacts. No filesystem access, model inference, or publication occurs.
    A missing path in an incomplete snapshot remains an uncertainty.
    """
    actions = candidate.build_spec.actions
    accepted = set(accepted_requirements)
    allowed = set(allowed_paths)
    findings: list[ScannerFinding] = []
    seen: set[tuple[str, str]] = set()

    def add(
        category: str,
        disposition: str,
        location: str,
        message: str,
        *,
        requirement: str = "",
        owner: str = "Planning",
        evidence: str = "",
    ) -> None:
        key = (category, location)
        if key in seen:
            return
        seen.add(key)
        findings.append(
            ScannerFinding(
                finding_id=f"plan:{candidate.candidate_id}:{category}:{len(findings) + 1}",
                capability="plan_structure",
                severity="error" if disposition == "blocking" else "warning",
                message=message,
                location=location,
                evidence_ref=evidence or f"{source_id}:{location}",
                category=category,
                disposition=disposition,
                owner_stage=owner,
                affected_requirement=requirement,
            )
        )

    for msg in validate_action_graph(candidate.build_spec):
        add("dependency_order", "blocking", "plan.actions", msg)

    for msg in validate_phase_graph(candidate.build_spec):
        add("dependency_order", "blocking", "plan.phases", msg)

    for msg in validate_spec_coverage(candidate.build_spec):
        add("missing_acceptance_check", "blocking", "plan.coverage", msg)

    by_path: dict[str, list[BuildAction]] = {}
    for action in actions:
        path = getattr(action, "source_path", None) or getattr(action, "target_path", None)
        if not isinstance(path, str):
            continue
        by_path.setdefault(path, []).append(action)
        for rid in action.requirement_ids:
            if rid not in accepted:
                add(
                    "unauthorized_scope", "blocking", f"plan.actions.{action.action_id}",
                    f"action refers to an unaccepted requirement: {rid}", requirement=str(rid),
                    evidence=f"{source_id}:accepted_requirements",
                )
        if path not in allowed:
            add(
                "unauthorized_scope", "blocking", f"plan.actions.{action.action_id}",
                f"action targets a path outside authorized scope: {path}",
                requirement=str(action.requirement_ids[0]),
                evidence=f"{source_id}:allowed_paths",
            )
        kind = action.action_kind
        if kind in ("modify", "remove", "move"):
            content = source_files.get(path)
            if content is None:
                add(
                    "invalid_action_target" if source_snapshot_complete else "unknown_source",
                    "blocking" if source_snapshot_complete else "uncertainty",
                    f"plan.actions.{action.action_id}",
                    f"source path not present in snapshot: {path}",
                    requirement=str(action.requirement_ids[0]),
                    owner="Planning" if source_snapshot_complete else "Audit Discovery",
                )
            elif sha256(content.encode("utf-8")).hexdigest() != getattr(action, "expected_source_digest", None):
                add(
                    "source_drift", "blocking", f"plan.actions.{action.action_id}",
                    f"source digest mismatch: {path}", requirement=str(action.requirement_ids[0]),
                    evidence=f"{source_id}:{path}",
                )
        elif kind == "create" and path in source_files:
            add(
                "invalid_action_target", "blocking", f"plan.actions.{action.action_id}",
                f"create target already exists: {path}", requirement=str(action.requirement_ids[0]),
            )

    for path, related in by_path.items():
        if len(related) < 2:
            continue
        if any(a.action_kind == "remove" for a in related) and any(
            a.action_kind != "remove" for a in related
        ):
            add(
                "conflicting_file_actions", "blocking", f"plan.actions.{path}",
                f"remove and non-remove actions target the same file: {path}",
                evidence=f"{source_id}:{path}",
            )

    for rid in accepted_requirements:
        if not any(rid in a.requirement_ids for a in actions):
            covered = any(
                cov.requirement_id == rid
                and cov.status == "covered"
                and any(ref in source_files for ref in cov.specification_refs)
                for cov in candidate.build_spec.requirement_coverage
            )
            if not covered:
                add(
                    "missing_requirement_coverage", "blocking", f"plan.requirements.{rid}",
                    "accepted requirement has neither planned action nor source-backed coverage",
                    requirement=rid, evidence=f"{source_id}:accepted_requirements",
                )

    criteria = required_criteria or {}
    for rid, criterion_ids in criteria.items():
        for cid in criterion_ids:
            linked = [
                a for a in actions if rid in a.requirement_ids and cid in a.acceptance_criteria_ids
            ]
            covered = any(
                c.requirement_id == rid and c.criterion_id == cid
                and c.status == "covered" and bool(c.validation_step_refs)
                for c in candidate.build_spec.criterion_coverage
            )
            if not (covered or any(a.validation_steps for a in linked)):
                add(
                    "missing_acceptance_check", "blocking", f"plan.criteria.{cid}",
                    "accepted criterion has no planned validation step",
                    requirement=rid, evidence=f"{source_id}:success_criteria",
                )

    return tuple(findings)


def repair_plan_draft(
    candidate: CandidateSpecification,
    directives: tuple[DraftRepair, ...],
    source_files: Mapping[str, str],
    *,
    allowed_paths: tuple[str, ...],
) -> CandidateSpecification:
    """Planner-controlled draft-only transformation; does not write source or approve.

    Every directive must be explicit and evidence-backed. The caller must rescan
    and persist the returned NEW revision through the existing artifact store.
    """
    if not directives:
        raise ValueError("at least one repair directive is required")
    actions = list(candidate.build_spec.actions)
    allowed = set(allowed_paths)
    for directive in directives:
        matching = [idx for idx, action in enumerate(actions) if action.action_id == directive.action_id]
        if len(matching) != 1:
            raise ValueError(f"action to repair not uniquely present: {directive.action_id}")
        index = matching[0]
        action = actions[index]
        if directive.kind == "remove_action":
            if len(actions) == 1:
                raise ValueError("cannot remove the only planned action")
            if any(directive.action_id in a.depends_on for a in actions if a.action_id != directive.action_id):
                raise ValueError("cannot remove an action referenced by another action")
            actions.pop(index)
        elif directive.kind == "set_dependencies":
            if directive.action_id in directive.dependencies:
                raise ValueError("self dependency is forbidden")
            if not set(directive.dependencies).issubset({a.action_id for a in actions}):
                raise ValueError("unknown repair dependency")
            actions[index] = action.model_copy(update={"depends_on": directive.dependencies})
        elif directive.kind == "restore_source_path":
            if action.action_kind not in ("modify", "move", "remove"):
                raise ValueError("source restoration requires an existing-file action")
            if directive.source_path not in allowed or directive.source_path not in source_files:
                raise ValueError("repair source is not supported by authorized evidence")
            actions[index] = action.model_copy(
                update={
                    "source_path": directive.source_path,
                    "expected_source_digest": sha256(source_files[directive.source_path].encode()).hexdigest(),
                }
            )
        else:
            raise ValueError("unsupported repair operation")
    rebuilt = candidate.build_spec.model_copy(update={"actions": tuple(actions)})
    repaired = candidate.model_copy(
        update={"specification_revision": candidate.specification_revision + 1, "build_spec": rebuilt}
    )
    result = CandidateSpecification.model_validate(repaired.model_dump())
    if validate_action_graph(result.build_spec):
        raise ValueError("repair leaves an invalid dependency graph")
    return result

def plan_structure_detector(
    source_files: Mapping[str, str],
    *,
    source_id: str,
    accepted_requirements: tuple[str, ...],
    allowed_paths: tuple[str, ...],
    required_criteria: Mapping[str, tuple[str, ...]] | None = None,
    source_snapshot_complete: bool = False,
) -> Callable[[bytes], tuple[ScannerFinding, ...]]:
    """Adapt the existing ScannerGateway detector API without another runtime."""
    def detect(candidate_bytes: bytes) -> tuple[ScannerFinding, ...]:
        candidate = CandidateSpecification.model_validate_json(candidate_bytes)
        return scan_plan_draft(
            candidate,
            source_files,
            source_id=source_id,
            accepted_requirements=accepted_requirements,
            allowed_paths=allowed_paths,
            required_criteria=required_criteria,
            source_snapshot_complete=source_snapshot_complete,
        )

    return detect

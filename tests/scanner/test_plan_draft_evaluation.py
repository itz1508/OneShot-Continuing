"""Planning draft scanner: source-grounded matched controls and draft-only repairs.

The tests intentionally derive expected results from source and accepted requirements.
These are synthetic cases; no inference about production build-success probability.
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from agent.contracts.common import ArtifactRef
from agent.contracts.planning import (
    BuildSpecification,
    CandidateSpecification,
    ModifyAction,
    PlanAssumption,
    RemoveAction,
    RequirementCoverage,
)
from agent.contracts.validation.planning import (
    DraftRepair,
    plan_structure_detector,
    repair_plan_draft,
    scan_plan_draft,
)
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.scanner_gateway import ScannerGateway

SOURCE = "def normalize(value):\n    return value\n"
OTHER = "def existing_feature():\n    return True\n"
FILES = {"app/main.py": SOURCE, "app/existing.py": OTHER}
ALLOWED = ("app/main.py", "app/existing.py", "app/missing.py")


def modify(
    aid: str = "A1",
    path: str = "app/main.py",
    *,
    requirement: str = "REQ-001",
    depends: tuple[str, ...] = (),
    digest: str | None = None,
) -> ModifyAction:
    return ModifyAction(
        action_id=aid,
        requirement_ids=(requirement,),
        acceptance_criteria_ids=("AC-001",),
        code_intent_ids=("intent-1",),
        preconditions=("source snapshot recorded",),
        depends_on=depends,
        validation_steps=("run acceptance check AC-001",),
        expected_result="confirmed expected behavior",
        recovery_requirement="restore source snapshot",
        source_path=path,
        expected_source_digest=digest or sha256(FILES.get(path, SOURCE).encode()).hexdigest(),
    )


def candidate(
    *actions: ModifyAction | RemoveAction,
    coverage: tuple[RequirementCoverage, ...] = (),
    assumptions: tuple[PlanAssumption, ...] = (),
) -> CandidateSpecification:
    return CandidateSpecification(
        candidate_id="fixture-candidate",
        specification_revision=1,
        build_spec=BuildSpecification(
            spec_id="spec-001",
            objective="Implement the accepted behavior",
            actions=actions,
            requirement_coverage=coverage,
            assumptions=assumptions,
        ),
    )


def scan(
    plan: CandidateSpecification,
    *,
    files: dict[str, str] | None = None,
    allowed: tuple[str, ...] = ALLOWED,
    accepted: tuple[str, ...] = ("REQ-001",),
    criteria: dict[str, tuple[str, ...]] | None = None,
    complete: bool = True,
    verified_evidence_refs: tuple[str, ...] = (),
):
    return scan_plan_draft(
        plan,
        files if files is not None else FILES,
        source_id="fixture:pinned-source",
        accepted_requirements=accepted,
        allowed_paths=allowed,
        required_criteria=criteria,
        source_snapshot_complete=complete,
        verified_evidence_refs=verified_evidence_refs,
    )


def categories(findings):
    return {item.category for item in findings}


def test_matched_single_file_valid_and_missing_target():
    sufficient = candidate(modify())
    defective = candidate(modify(path="app/missing.py"))
    assert scan(sufficient) == ()
    assert categories(scan(defective)) == {"invalid_action_target"}


def test_matched_multifile_chain_and_missing_dependency_edge():
    sufficient = candidate(modify(), modify("A2", "app/existing.py", depends=("A1",)))
    defective = candidate(modify(), modify("A2", "app/existing.py", depends=("not-in-plan",)))
    assert scan(sufficient) == ()
    assert categories(scan(defective)) == {"dependency_order"}


def test_existing_satisfied_requirement_needs_no_redundant_action():
    sufficient = candidate(
        modify(),
        coverage=(
            RequirementCoverage(
                requirement_id="REQ-002",
                status="covered",
                criterion_refs=("AC-002",),
                specification_refs=("app/existing.py",),
                reason="verified in pinned source",
            ),
        ),
    )
    defective = candidate(modify())
    assert scan(sufficient, accepted=("REQ-001", "REQ-002")) == ()
    assert categories(scan(defective, accepted=("REQ-001", "REQ-002"))) == {"missing_requirement_coverage"}


def test_missing_accepted_criterion_and_planned_check():
    accepted = {"REQ-001": ("AC-001",)}
    sufficient = candidate(modify())
    defective_action = modify().model_copy(update={"acceptance_criteria_ids": ("AC-002",)})
    defective = candidate(defective_action)
    assert scan(sufficient, criteria=accepted) == ()
    assert categories(scan(defective, criteria=accepted)) == {"missing_acceptance_check"}


def test_out_of_scope_action_is_not_a_naming_issue():
    sufficient = candidate(modify())
    out_of_scope = candidate(modify(path="app/existing.py"))
    assert scan(sufficient, allowed=("app/main.py",)) == ()
    assert categories(scan(out_of_scope, allowed=("app/main.py",))) == {"unauthorized_scope"}
    # Authorization is independent from the source target's existence.
    assert all(f.owner_stage == "Planning" for f in scan(out_of_scope, allowed=("app/main.py",)))


def test_remove_and_modify_same_source_conflicts():
    remove = RemoveAction(
        action_id="A2",
        requirement_ids=("REQ-001",),
        acceptance_criteria_ids=("AC-001",),
        code_intent_ids=("intent-1",),
        preconditions=("source snapshot recorded",),
        validation_steps=("run acceptance check AC-001",),
        expected_result="remove obsolete path",
        recovery_requirement="restore snapshot",
        source_path="app/main.py",
        expected_source_digest=sha256(SOURCE.encode()).hexdigest(),
        destructive_approval_requirement="separate approval required",
    )
    sufficient = candidate(modify())
    defective = candidate(modify(), remove)
    assert scan(sufficient) == ()
    assert categories(scan(defective)) == {"conflicting_file_actions"}


def test_digest_drift_requires_matching_snapshot():
    correct = candidate(modify())
    stale = candidate(modify(digest="f" * 64))
    assert scan(correct) == ()
    assert categories(scan(stale)) == {"source_drift"}


def test_unknown_source_stays_unknown_with_auditor_owner():
    plan = candidate(modify(path="app/missing.py"))
    unknown = scan(plan, complete=False)
    assert categories(unknown) == {"unknown_source"}
    assert unknown[0].disposition == "uncertainty"
    assert unknown[0].owner_stage == "Audit Discovery"
    assert categories(scan(plan, complete=True)) == {"invalid_action_target"}


def test_cosmetic_grammar_does_not_change_finding():
    original = candidate(modify())
    renamed_prose = original.model_copy(update={"planning_report": "Fix teh endpoint lable."})
    assert scan(original) == scan(renamed_prose) == ()


def test_repair_is_separate_new_draft_revision_and_rescan():
    defective = candidate(modify(path="app/missing.py"))
    assert categories(scan(defective)) == {"invalid_action_target"}
    repaired = repair_plan_draft(
        defective,
        (
            DraftRepair(
                action_id="A1",
                kind="restore_source_path",
                source_path="app/main.py",
                evidence_ref="fixture:pinned-source:app/main.py",
            ),
        ),
        FILES,
        allowed_paths=ALLOWED,
        verified_evidence_refs=("fixture:pinned-source:app/main.py",),
    )
    assert repaired.specification_revision == 2
    assert defective.specification_revision == 1
    assert defective.build_spec.actions[0].source_path == "app/missing.py"
    assert repaired.build_spec.actions[0].source_path == "app/main.py"
    assert scan(repaired) == ()


def test_repair_refuses_unverified_or_unauthorized_source():
    defective = candidate(modify(path="app/missing.py"))
    with pytest.raises(ValueError, match="authorized evidence"):
        repair_plan_draft(
            defective,
            (
                DraftRepair(
                    action_id="A1",
                    kind="restore_source_path",
                    source_path="external/private.py",
                    evidence_ref="unverified",
                ),
            ),
            FILES,
            allowed_paths=ALLOWED,
            verified_evidence_refs=("unverified",),
        )


def test_repair_dependency_then_rescan_without_source_change():
    original = candidate(modify(), modify("A2", "app/existing.py", depends=("missing",)))
    assert "dependency_order" in categories(scan(original))
    repaired = repair_plan_draft(
        original,
        (
            DraftRepair(
                action_id="A2",
                kind="set_dependencies",
                dependencies=("A1",),
                evidence_ref="fixture:dependency-trace",
            ),
        ),
        FILES,
        allowed_paths=ALLOWED,
        verified_evidence_refs=("fixture:dependency-trace",),
    )
    assert scan(repaired) == ()
    assert original.build_spec.actions[1].depends_on == ("missing",)


def test_existing_gateway_uses_immutable_artifact_and_registered_detector(tmp_path):
    plan = candidate(modify())
    store = ArtifactStore(tmp_path)
    digest = store.put_immutable(plan, "fixture-plan", 1, "planning", "1.0")
    ref = ArtifactRef(
        artifact_id="fixture-plan",
        artifact_revision=1,
        artifact_digest=digest,
        contract_id="planning",
        contract_version="1.0",
        serializer_profile="rfc8785-jcs-sha256-v1",
    )
    gateway = ScannerGateway(store)
    gateway.register_detector(
        "plan_structure",
        plan_structure_detector(
            FILES,
            source_id="fixture:pinned-source",
            accepted_requirements=("REQ-001",),
            allowed_paths=ALLOWED,
            source_snapshot_complete=True,
        ),
    )
    result = gateway.scan_exact(ref, "fixture-repo", ("plan_structure",))
    assert result.outcome.value == "pass"
    assert result.findings == ()


def test_recoverable_unknown_assumption_is_carried_not_fabricated():
    plan = candidate(
        modify(),
        assumptions=(
            PlanAssumption(
                assumption_id="assumption-001",
                requirement_id="REQ-001",
                statement="Provider endpoint is available in deployment environment",
                status="unknown",
                verification_stage="Preflight",
            ),
        ),
    )
    findings = scan(plan)
    assert categories(findings) == {"unresolved_assumption"}
    assert findings[0].disposition == "uncertainty"
    assert findings[0].owner_stage == "Preflight"


def test_unsupported_assumption_does_not_become_verified_by_self_claim():
    plan = candidate(
        modify(),
        assumptions=(
            PlanAssumption(
                assumption_id="assumption-001",
                requirement_id="REQ-001",
                statement="Provider reports expected schema",
                status="supported",
                evidence_refs=("research:provider-schema",),
            ),
        ),
    )
    findings = scan(plan)
    assert categories(findings) == {"unsupported_evidence_claim"}
    assert findings[0].disposition == "blocking"

    observed = scan(plan, verified_evidence_refs=("research:provider-schema",))
    assert observed == ()


def test_plan_repair_rejects_fabricated_evidence_reference():
    defective = candidate(modify(path="app/missing.py"))
    with pytest.raises(ValueError, match="not independently verified"):
        repair_plan_draft(
            defective,
            (
                DraftRepair(
                    action_id="A1",
                    kind="restore_source_path",
                    source_path="app/main.py",
                    evidence_ref="fixture:invented-source-ref",
                ),
            ),
            FILES,
            allowed_paths=ALLOWED,
            verified_evidence_refs=("fixture:pinned-source:app/main.py",),
        )

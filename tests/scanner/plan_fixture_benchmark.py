"""Execute synthetic plan fixtures against the native Planning scanner contract.

This is an evaluation-only bridge, not a runtime adapter or evidence authority.
Upstream fixture labels are loaded only AFTER calling the native scanner.
Mandatory native fields absent from the synthetic schema are explicitly marked
non-authoritative; they must not be used for Build Admission.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from agent.contracts.planning import (
    BuildSpecification,
    CandidateSpecification,
    ModifyAction,
    PlanAssumption,
    RemoveAction,
)
from agent.contracts.validation.planning import scan_plan_draft

DATA = Path(__file__).resolve().parents[1] / "fixtures" / "plan_scanner"


def load(name: str, key: str) -> dict[str, Any]:
    return json.loads((DATA / name).read_text(encoding="utf-8"))[key]


def adapt(case_id: str, item: dict[str, Any]) -> tuple[CandidateSpecification, dict[str, str], list[str]]:
    """Preserve fixture actions without treating synthetic adapter defaults as evidence."""
    plan = item["plan"]
    action_rows = plan["file_actions"]
    checks = plan["acceptance_checks"]
    if not action_rows:
        raise ValueError("unrepresentable: BuildSpecification requires at least one action")
    if not checks:
        raise ValueError("unrepresentable: native ActionBase requires recorded validation steps")
    snapshots = item["source_snapshot"]
    sources = {path: value["content"] for path, value in snapshots.items()}
    for path, value in snapshots.items():
        if sha256(value["content"].encode("utf-8")).hexdigest() != value["sha256"]:
            raise ValueError(f"unrepresentable: source digest mismatch at {path}")

    adapter_limits = [
        "synthetic fixture has no CodeIntent/preconditions/recovery receipts; non-authoritative placeholders used",
        "source snapshot completeness is unverified, so missing source paths remain uncertainty",
    ]
    actions = []
    for row in action_rows:
        aid = row["action_id"]
        related_tasks = [task for task in plan["tasks"] if aid in task["action_refs"]]
        if not related_tasks:
            raise ValueError(f"unrepresentable: action {aid} has no fixture task mapping")
        requirement_ids = tuple(sorted({rid for task in related_tasks for rid in task["requirement_refs"]}))
        if not requirement_ids:
            raise ValueError(f"unrepresentable: action {aid} has no requirement mapping")
        relevant_checks = [check for check in checks if check["requirement_ref"] in requirement_ids]
        if not relevant_checks:
            raise ValueError(f"unrepresentable: action {aid} has no validation check")
        path = row["path"]
        digest = snapshots[path]["sha256"] if path in snapshots else sha256(b"").hexdigest()
        if path not in snapshots:
            adapter_limits.append(
                f"{aid}: no source digest in fixture for {path}; synthetic empty-content marker is not evidence"
            )
        fields = {
            "action_id": aid,
            "requirement_ids": requirement_ids,
            "acceptance_criteria_ids": tuple(check["check_id"] for check in relevant_checks),
            "code_intent_ids": tuple(f"synthetic:{task['task_id']}" for task in related_tasks),
            "preconditions": ("synthetic:source-inspection-not-authorized",),
            "depends_on": tuple(row["depends_on"]),
            "validation_steps": tuple(check["expected_observation"] for check in relevant_checks),
            "expected_result": row["detail"],
            "recovery_requirement": "synthetic:recovery-not-authorized",
            "source_path": path,
            "expected_source_digest": digest,
        }
        if row["operation"] == "modify":
            actions.append(ModifyAction(**fields))
        elif row["operation"] == "remove":
            actions.append(
                RemoveAction(
                    **fields,
                    destructive_approval_requirement="synthetic:separate-approval-required",
                )
            )
        else:
            raise ValueError(f"unrepresentable: unmapped action operation {row['operation']}")

    assumptions = tuple(
        PlanAssumption(
            assumption_id=f"assumption-{idx}",
            requirement_id=item["accepted_requirements"][0]["id"],
            statement=assumption["claim"],
            status="supported" if assumption["status"] == "verified" else "unknown",
            evidence_refs=(),
            verification_stage=assumption["owner_stage"],
        )
        for idx, assumption in enumerate(plan["assumptions"], start=1)
    )
    candidate = CandidateSpecification(
        candidate_id=case_id.replace("/", "-"),
        specification_revision=plan["revision"],
        build_spec=BuildSpecification(
            spec_id=f"synthetic-{case_id.replace('/', '-')}",
            objective=item["intent"],
            actions=tuple(actions),
            assumptions=assumptions,
        ),
    )
    return candidate, sources, adapter_limits


def score(records: list[dict[str, Any]], split: str) -> dict[str, Any]:
    selected = [row for row in records if row["split"] == split]
    evaluated = [row for row in selected if row["status"] == "evaluated"]
    tp = sum(row["expected_actionable"] and row["observed_blocking"] for row in evaluated)
    fp = sum(not row["expected_actionable"] and row["observed_blocking"] for row in evaluated)
    fn = sum(row["expected_actionable"] and not row["observed_blocking"] for row in evaluated)
    tn = sum(not row["expected_actionable"] and not row["observed_blocking"] for row in evaluated)
    exact = sum(row["expected_findings"] == row["observed_findings"] for row in evaluated)
    return {
        "total": len(selected),
        "evaluated": len(evaluated),
        "unrepresentable": len(selected) - len(evaluated),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "exact_finding_matches": exact,
    }


def run() -> dict[str, Any]:
    inputs = load("inputs.json", "inputs")
    # Ground truth intentionally not consulted during adaptation or scanning.
    observed: dict[str, dict[str, Any]] = {}
    for key, item in sorted(inputs.items()):
        try:
            candidate, sources, adapter_limits = adapt(key, item)
            findings = scan_plan_draft(
                candidate,
                sources,
                source_id=f"synthetic:{key}",
                accepted_requirements=tuple(req["id"] for req in item["accepted_requirements"]),
                allowed_paths=tuple(item["scope"]["allowed_paths"]),
                required_criteria={
                    req["id"]: tuple(
                        check["check_id"]
                        for check in item["plan"]["acceptance_checks"]
                        if check["requirement_ref"] == req["id"]
                    )
                    for req in item["accepted_requirements"]
                },
                source_snapshot_complete=False,
                verified_evidence_refs=(),
            )
            observed[key] = {
                "status": "evaluated",
                "observed_blocking": any(f.disposition == "blocking" for f in findings),
                "observed_findings": sorted(
                    [
                        {
                            "category": f.category,
                            "disposition": f.disposition,
                            "owner_stage": f.owner_stage,
                        }
                        for f in findings
                    ],
                    key=lambda v: (v["category"], v["disposition"], v["owner_stage"]),
                ),
                "adapter_limits": adapter_limits,
            }
        except ValueError as exc:
            observed[key] = {
                "status": "unrepresentable",
                "reason": str(exc),
                "observed_blocking": None,
                "observed_findings": [],
            }
    truth = load("ground_truth.json", "ground_truth")
    expected_keys = {f"{family}/{variant}" for family in truth for variant in ("a", "b")}
    if set(observed) != expected_keys:
        raise ValueError("fixture input and ground truth identifiers do not match")
    records = []
    for key, result in sorted(observed.items()):
        family, variant = key.split("/")
        truth_case = truth[family]
        variant_truth = truth_case["variants"][variant]
        expected_findings = sorted(
            [
                {
                    "category": finding["category"],
                    "disposition": finding["disposition"],
                    "owner_stage": finding["owner_stage"],
                }
                for finding in variant_truth["expected_findings"]
            ],
            key=lambda v: (v["category"], v["disposition"], v["owner_stage"]),
        )
        records.append(
            {
                "case_id": key,
                "split": truth_case["split"],
                "expected_actionable": variant_truth["actionable_defect"],
                "expected_findings": expected_findings,
                **result,
            }
        )
    if len(records) != 24:
        raise ValueError(f"benchmark inventory is incomplete: {len(records)}")
    return {
        "benchmark": "OneShot synthetic plan scanner fixture v1",
        "scorer": "blocking vs ground_truth.actionable_defect; findings require exact category/disposition/owner",
        "limits": [
            "synthetic generated plans; not independent hold-out labels or production validation",
            "unrepresentable inputs excluded from denominators and reported individually",
            "no host-verified receipts; no source completeness guarantee",
        ],
        "summary": {split: score(records, split) for split in ("development", "held_out")}
        | {"all": score_all(records)},
        "records": records,
    }


def score_all(records: list[dict[str, Any]]) -> dict[str, Any]:
    combined = [{**row, "split": "all"} for row in records]
    return score(combined, "all")


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))

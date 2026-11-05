"""Host boundary for canonical Gap Analysis.

Analysis belongs to :mod:`agent.gap_analysis`. This module only verifies
immutable inputs, invokes the trusted walking-skeleton runner, persists the
result, and issues a completion receipt for a valid result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent.contracts.common import ArtifactRef, ContractModel, StepStatus
from agent.contracts.host import ReceiptRef
from agent.gap_analysis import (
    ComparableSystemAnalysis,
    GapAnalyzer,
    GapBacktestCorpus,
    RegistrySnapshotSet,
    SourceGroundedAnalysis,
    StructuralGapRequest,
    StructuralGapResult,
    WalkingSkeletonObservation,
    WorkflowConcernMatrix,
    WorkflowContractBundle,
    WorkflowExecutionTrace,
)
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.receipt_store import ReceiptStore

__all__ = (
    "HostGapAnalyzer",
    "SkeletonRunner",
    "StructuralGapError",
    "StructuralGapOutcome",
    "StructuralGapRequest",
    "StructuralGapResult",
    "structural_gap_receipt_subject",
)


class StructuralGapError(RuntimeError):
    """A required structural input or its evidence cannot be verified."""


@dataclass(frozen=True)
class StructuralGapOutcome:
    result: StructuralGapResult
    result_ref: ArtifactRef
    completion_receipt_ref: ReceiptRef | None


SkeletonRunner = Callable[[StructuralGapRequest], WalkingSkeletonObservation]


def structural_gap_receipt_subject(result: StructuralGapResult, digest: str) -> str:
    """Bind a host receipt to the exact candidate and analysis result."""
    return (
        f"structural_gap_pass:{result.task_id}:{result.run_id}:"
        f"{result.request_id}:{result.request_revision}:"
        f"{result.candidate_specification_ref.artifact_digest}:{digest}"
    )


def verify_structural_pass(
    artifacts: ArtifactStore,
    receipts: ReceiptStore,
    task_id: str,
    run_id: str,
    result_ref: ArtifactRef,
    receipt_ref: ReceiptRef,
    candidate_ref: ArtifactRef | None = None,
) -> StructuralGapResult:
    """Recheck the exact structural pass before Scanner, freeze, or transition."""
    if receipt_ref.issuer_id != "host" or result_ref.contract_id != "structural_analysis_result":
        raise StructuralGapError("invalid structural gap provenance")
    raw = artifacts.get_verified(result_ref.artifact_id, result_ref.artifact_revision)
    if artifacts.get_digest(result_ref.artifact_id, result_ref.artifact_revision) != result_ref.artifact_digest:
        raise StructuralGapError("structural gap result digest mismatch")
    result = StructuralGapResult.model_validate_json(raw)
    if (result.task_id, result.run_id) != (task_id, run_id):
        raise StructuralGapError("structural gap result belongs to another task or run")
    if result.execution_status is not StepStatus.COMPLETED or result.findings:
        raise StructuralGapError("structural gap analysis did not pass")
    if result.known_critical_gap_detection_rate != 1.0 or not result.walking_skeleton_completed:
        raise StructuralGapError("structural backtest or walking skeleton incomplete")
    candidate = result.candidate_specification_ref
    if candidate_ref is not None and candidate != candidate_ref:
        raise StructuralGapError("structural pass belongs to another candidate")
    if artifacts.get_digest(candidate.artifact_id, candidate.artifact_revision) != candidate.artifact_digest:
        raise StructuralGapError("Planning candidate changed since structural analysis")
    if not receipts.verify(
        receipt_ref.receipt_id,
        receipt_ref.receipt_digest,
        structural_gap_receipt_subject(result, result_ref.artifact_digest),
    ):
        raise StructuralGapError("structural gap completion receipt is not verified")
    return result


class HostGapAnalyzer:
    """Verify and persist canonical Gap Analysis without owning its decisions."""

    def __init__(self, artifacts: ArtifactStore, receipts: ReceiptStore) -> None:
        self._artifacts = artifacts
        self._receipts = receipts
        self._analyzer = GapAnalyzer()

    def _get(self, ref: ArtifactRef, model: type[ContractModel]) -> ContractModel:
        try:
            content = self._artifacts.get_verified(ref.artifact_id, ref.artifact_revision)
            digest = self._artifacts.get_digest(ref.artifact_id, ref.artifact_revision)
            if digest != ref.artifact_digest:
                raise StructuralGapError(f"artifact digest mismatch: {ref.artifact_id}")
            return model.model_validate_json(content)
        except StructuralGapError:
            raise
        except Exception as exc:
            raise StructuralGapError(f"cannot validate {ref.artifact_id}: {exc}") from exc

    def _verify(self, ref: ArtifactRef) -> None:
        if self._artifacts.get_digest(ref.artifact_id, ref.artifact_revision) != ref.artifact_digest:
            raise StructuralGapError(f"missing or mismatched artifact: {ref.artifact_id}")
        self._artifacts.get_verified(ref.artifact_id, ref.artifact_revision)

    def evaluate(
        self,
        request: StructuralGapRequest,
        *,
        walking_skeleton_runner: SkeletonRunner | None = None,
    ) -> StructuralGapOutcome:
        """Load exact inputs, delegate analysis, and persist the result."""
        self._verify(request.candidate_specification_ref)
        workflow = self._get(request.workflow_contract_bundle_ref, WorkflowContractBundle)
        registry = self._get(request.registry_snapshot_set_ref, RegistrySnapshotSet)
        trace = self._get(request.workflow_trace_ref, WorkflowExecutionTrace)
        matrix = self._get(request.concern_matrix_ref, WorkflowConcernMatrix)
        corpus = self._get(request.backtest_corpus_ref, GapBacktestCorpus)
        grounded = self._get(request.source_grounded_analysis_ref, SourceGroundedAnalysis)
        comparable = self._get(request.comparable_system_analysis_ref, ComparableSystemAnalysis)
        assert isinstance(workflow, WorkflowContractBundle)
        assert isinstance(registry, RegistrySnapshotSet)
        assert isinstance(trace, WorkflowExecutionTrace)
        assert isinstance(matrix, WorkflowConcernMatrix)
        assert isinstance(corpus, GapBacktestCorpus)
        assert isinstance(grounded, SourceGroundedAnalysis)
        assert isinstance(comparable, ComparableSystemAnalysis)

        for case in corpus.historical_cases:
            self._verify(case.case_evidence_ref)
        self._verify(grounded.source_snapshot_ref)
        for ref in (*grounded.evidence_refs, *comparable.evidence_refs):
            self._verify(ref)

        skeleton = self._run_skeleton(request, walking_skeleton_runner)
        result = self._analyzer.analyze(
            request,
            workflow,
            registry,
            trace,
            matrix,
            corpus,
            grounded,
            comparable,
            skeleton,
        )
        return self._persist(result)

    def _run_skeleton(
        self,
        request: StructuralGapRequest,
        runner: SkeletonRunner | None,
    ) -> WalkingSkeletonObservation | None:
        if runner is None:
            return None
        try:
            observation = runner(request)
        except Exception as exc:
            return WalkingSkeletonObservation(completed=False, error=f"execution failed: {exc}")
        if observation.evidence_ref is not None:
            self._verify(observation.evidence_ref)
        return observation

    def _persist(self, result: StructuralGapResult) -> StructuralGapOutcome:
        result_id = (
            f"structural-gap-{result.task_id}-{result.run_id}-{result.candidate_specification_ref.artifact_digest}"
        )
        digest = self._artifacts.put_immutable(result, result_id, 1, "structural_analysis_result", "1.0")
        result_ref = ArtifactRef(
            artifact_id=result_id,
            artifact_revision=1,
            artifact_digest=digest,
            contract_id="structural_analysis_result",
            contract_version="1.0",
            serializer_profile="rfc8785-jcs-sha256-v1",
        )
        if result.execution_status is not StepStatus.COMPLETED or result.findings:
            return StructuralGapOutcome(result=result, result_ref=result_ref, completion_receipt_ref=None)

        receipt_id = f"gap-pass-{result_id}"
        _, receipt_digest = self._receipts.issue_verified(
            receipt_id,
            "host",
            structural_gap_receipt_subject(result, digest),
        )
        receipt = ReceiptRef(receipt_id=receipt_id, receipt_digest=receipt_digest, issuer_id="host")
        return StructuralGapOutcome(result=result, result_ref=result_ref, completion_receipt_ref=receipt)

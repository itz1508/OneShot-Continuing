"""Host controller — single transition authority for all stages."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from agent.contracts.common import ArtifactRef
from agent.contracts.host import HostDispatchEnvelope, HostDispatchResult, ReceiptRef
from agent.contracts.scanner import ScannerEvidence
from agent.contracts.work_todo import TodoList, WorkBinding
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.authorization import AuthorizationEngine
from agent.runtime.canonical_serialization import SERIALIZER_PROFILE
from agent.runtime.checkpoint_store import CheckpointStore, CompetingWriterError
from agent.runtime.event_store import EventStore
from agent.runtime.host_gap_analyzer import (
    HostGapAnalyzer,
    SkeletonRunner,
    StructuralGapOutcome,
    StructuralGapRequest,
    StructuralGapResult,
    verify_structural_pass,
)
from agent.runtime.providers.registry import ProviderRegistry
from agent.runtime.receipt_store import ReceiptStore
from agent.runtime.recovery import BoundedRecovery
from agent.runtime.scanner_check_registry import ScannerCheckRegistry
from agent.runtime.scanner_evidence import ScannerScanOutcome, persist_scan_result, verify_scanner_evidence
from agent.runtime.scanner_gateway import ScannerGateway
from agent.runtime.work_todo import WorkTodoError, WorkTodoManager


class Stage(StrEnum):
    RESEARCH = "research"
    AUDIT_DISCOVERY = "audit_discovery"
    PLANNING = "planning"
    FIXTURE_VALIDATION = "fixture_validation"
    BUILD = "build"


STAGE_ORDER = (
    Stage.RESEARCH,
    Stage.AUDIT_DISCOVERY,
    Stage.PLANNING,
    Stage.FIXTURE_VALIDATION,
    Stage.BUILD,
)


class TransitionError(Exception):
    pass


class TaskState(BaseModel):
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    current_stage: Stage = Stage.RESEARCH
    completed_stages: tuple[Stage, ...] = ()
    active_work_artifact_id: str | None = None
    build_verification_artifact_id: str | None = None
    build_verification_digest: str | None = None
    planning_revision: int = Field(default=1, ge=1)

    model_config = {"frozen": True}


class HostController:
    """Single host transition authority.

    - Manages stage transitions and receipts.
    - Rejects illegal transitions.
    - Checkpoints state with CAS.
    - Dispatches to stores, scanner, and providers.
    """

    def __init__(
        self,
        state_root: str | Path,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.state_root = Path(state_root)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.artifact_store = ArtifactStore(self.state_root)
        self.receipt_store = ReceiptStore(self.state_root)
        self.event_store = EventStore(self.state_root)
        self.work_todos = WorkTodoManager(self.artifact_store, self.event_store)
        self.checkpoint_store = CheckpointStore(self.state_root)
        self.scanner = ScannerGateway(self.artifact_store)
        self.scanner_checks: ScannerCheckRegistry | None = None
        self.gap_analyzer = HostGapAnalyzer(self.artifact_store, self.receipt_store)
        self.recovery = BoundedRecovery()
        self.providers = ProviderRegistry()
        self.authorization = AuthorizationEngine(
            allowed_roots=(str(self.state_root),)
            if workspace_root is None
            else (str(workspace_root), str(self.state_root))
        )
        self._workspace_root = workspace_root or self.state_root / "workspace"

    def advance_stage(
        self,
        task_id: str,
        run_id: str,
        expected_stage: Stage,
        completion_receipt_ref: ReceiptRef | None = None,
        gap_result_ref: ArtifactRef | None = None,
        gap_receipt_ref: ReceiptRef | None = None,
        scanner_evidence: ScannerEvidence | None = None,
        todo_ref: ArtifactRef | None = None,
    ) -> TaskState:
        """Advance to the next stage if the current stage is completed.

        Requires a valid completion receipt from the current stage to
        prove the stage produced verified output before transitioning.
        """
        checkpoint = self.checkpoint_store.load_checkpoint(task_id)
        if checkpoint is None:
            state = TaskState(task_id=task_id, run_id=run_id)
        else:
            _rev, state_dict, _ = checkpoint
            state = TaskState(**state_dict)

        if state.current_stage != expected_stage:
            raise TransitionError(f"expected stage {expected_stage}, but current is {state.current_stage}")
        if state.run_id != run_id or state.task_id != task_id:
            raise TransitionError("stage transition task/run binding mismatch")

        receipt_artifact = self._verify_stage_receipt(state, completion_receipt_ref)
        if state.current_stage is Stage.PLANNING:
            gap_result = self._verify_structural_gap(task_id, run_id, gap_result_ref, gap_receipt_ref)
            self._verify_scanner_pass(task_id, run_id, gap_result.candidate_specification_ref, scanner_evidence)

        # Task tracking is a mandatory observation gate, never permission to execute.
        if todo_ref is None:
            raise TransitionError("completed work list reference required before stage transition")
        if state.active_work_artifact_id != todo_ref.artifact_id:
            raise TransitionError("work list does not match the host-assigned request")
        try:
            self.work_todos.require_complete(todo_ref, task_id=task_id, run_id=run_id, stage=state.current_stage.value)
        except WorkTodoError as exc:
            raise TransitionError(f"invalid or unfinished work list: {exc}") from exc
        self._verify_stage_evidence(receipt_artifact, todo_ref)

        idx = STAGE_ORDER.index(state.current_stage)
        if idx + 1 >= len(STAGE_ORDER):
            raise TransitionError("already at final stage")

        completed = (*state.completed_stages, state.current_stage)
        new_stage = STAGE_ORDER[idx + 1]
        new_state = TaskState(
            task_id=task_id,
            run_id=run_id,
            current_stage=new_stage,
            completed_stages=completed,
            planning_revision=state.planning_revision,
        )

        expected_rev = checkpoint[0] if checkpoint else 0
        try:
            self.checkpoint_store.checkpoint_cas(
                task_id,
                expected_rev,
                new_state.model_dump(mode="json"),
            )
        except CompetingWriterError as e:
            raise TransitionError(f"checkpoint CAS failed: {e}") from e

        self.event_store.append(
            task_id,
            "stage_transition",
            f"{state.current_stage} -> {new_stage}",
            event_id=f"stage-transition:{task_id}:{run_id}:{expected_rev + 1}",
        )
        return new_state

    def _verify_stage_receipt(self, state: TaskState, completion_receipt_ref: ReceiptRef | None) -> ArtifactRef:
        """Verify host provenance and exact stage artifact; never accept legacy subjects."""
        if completion_receipt_ref is None:
            raise TransitionError("stage completion receipt required")
        if completion_receipt_ref.issuer_id != "host":
            raise TransitionError("invalid completion receipt: untrusted issuer")
        subject = self.receipt_store.get_subject(completion_receipt_ref.receipt_id)
        prefix = f"stage_complete:{state.task_id}:{state.run_id}:{state.current_stage.value}:"
        if subject is None or not subject.startswith(prefix):
            raise TransitionError("invalid completion receipt: identity mismatch")
        try:
            artifact_id, revision_text, digest = subject[len(prefix) :].rsplit(":", 2)
            revision = int(revision_text)
        except (ValueError, AttributeError) as exc:
            raise TransitionError("invalid completion receipt: artifact identity") from exc
        if not artifact_id or revision < 1 or len(digest) != 64:
            raise TransitionError("invalid completion receipt: missing artifact evidence")
        if not self.receipt_store.verify(
            completion_receipt_ref.receipt_id,
            completion_receipt_ref.receipt_digest,
            subject,
        ):
            raise TransitionError("invalid completion receipt: unverified host provenance")
        try:
            if self.artifact_store.get_digest(artifact_id, revision) != digest:
                raise ValueError("artifact digest mismatch")
            self.artifact_store.get_verified(artifact_id, revision)
        except Exception as exc:
            raise TransitionError("invalid completion receipt: artifact not verified") from exc
        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_revision=revision,
            artifact_digest=digest,
            contract_id="stage_receipt_evidence",
            contract_version="1.0",
            serializer_profile="rfc8785-jcs-sha256-v1",
        )

    def _verify_stage_evidence(self, receipt_artifact: ArtifactRef, todo_ref: ArtifactRef) -> None:
        """Receipt must bind the completed work list or an artifact it actually cites."""
        if (
            receipt_artifact.artifact_id == todo_ref.artifact_id
            and receipt_artifact.artifact_revision == todo_ref.artifact_revision
            and receipt_artifact.artifact_digest == todo_ref.artifact_digest
        ):
            return
        work = self.work_todos.read(todo_ref)
        for action in work.actions:
            for ref in action.evidence_refs:
                if (
                    ref.artifact_id == receipt_artifact.artifact_id
                    and ref.artifact_revision == receipt_artifact.artifact_revision
                    and ref.artifact_digest == receipt_artifact.artifact_digest
                ):
                    return
        raise TransitionError("invalid completion receipt: evidence not in completed work")

    def _verify_structural_gap(
        self,
        task_id: str,
        run_id: str,
        gap_result_ref: ArtifactRef | None,
        gap_receipt_ref: ReceiptRef | None,
        candidate_ref: ArtifactRef | None = None,
    ) -> StructuralGapResult:
        """Verify a persisted result and trusted pass receipt for this exact candidate."""
        if gap_result_ref is None or gap_receipt_ref is None:
            raise TransitionError("structural gap analysis receipt and result required")
        try:
            return verify_structural_pass(
                self.artifact_store,
                self.receipt_store,
                task_id,
                run_id,
                gap_result_ref,
                gap_receipt_ref,
                candidate_ref,
            )
        except Exception as exc:
            raise TransitionError(f"invalid structural gap evidence: {exc}") from exc

    def configure_scanner_checks(self, registry_ref: ArtifactRef) -> None:
        """Load exact host-pinned check requirements; missing tools fail closed."""
        self.scanner_checks = ScannerCheckRegistry(self.artifact_store, registry_ref)

    def planning_ready_for_approval(
        self,
        task_id: str,
        run_id: str,
        candidate_ref: ArtifactRef,
        gap_result_ref: ArtifactRef | None,
        gap_receipt_ref: ReceiptRef | None,
        scanner_evidence: ScannerEvidence | None,
    ) -> bool:
        """Read-only host gate for the exact proposed Planning candidate."""
        self._verify_structural_gap(task_id, run_id, gap_result_ref, gap_receipt_ref, candidate_ref)
        self._verify_scanner_pass(task_id, run_id, candidate_ref, scanner_evidence)
        return True

    def _verify_scanner_pass(
        self,
        task_id: str,
        run_id: str,
        candidate_ref: ArtifactRef,
        evidence: ScannerEvidence | None,
    ) -> None:
        if self.scanner_checks is None or evidence is None:
            raise TransitionError("verified Scanner coverage required for Planning")
        try:
            verify_scanner_evidence(
                self.artifact_store,
                self.receipt_store,
                evidence,
                candidate_ref,
                self.scanner_checks,
                task_id,
                run_id,
            )
        except Exception as exc:
            raise TransitionError(f"invalid Scanner evidence: {exc}") from exc

    def scan_planning_candidate(
        self,
        task_id: str,
        run_id: str,
        candidate_ref: ArtifactRef,
        repository_identity: str,
        capabilities: tuple[str, ...],
        gap_result_ref: ArtifactRef | None,
        gap_receipt_ref: ReceiptRef | None,
    ) -> ScannerScanOutcome:
        """Host Scanner dispatch; always reject an unvalidated Planning candidate."""
        self._verify_structural_gap(task_id, run_id, gap_result_ref, gap_receipt_ref, candidate_ref)
        if self.scanner_checks is None:
            raise TransitionError("Scanner check registry is not configured")
        if not repository_identity:
            raise TransitionError("Scanner repository identity is required")
        required_capabilities = self.scanner_checks.required_capabilities
        if capabilities != required_capabilities:
            raise TransitionError("Scanner request does not cover the required registry checks")
        result = self.scanner.scan_exact(
            candidate_ref, repository_identity, required_capabilities, self.scanner_checks.ref
        ).model_copy(update={"task_id": task_id, "run_id": run_id})
        from agent.contracts.planning_coverage import planning_coverage
        from agent.contracts.validation.structural import CONCERNS

        result = result.model_copy(
            update={
                "planning_coverage": planning_coverage(
                    structural_concerns=CONCERNS,
                    scanner_capabilities=result.capabilities_checked,
                )
            }
        )
        return persist_scan_result(self.artifact_store, self.receipt_store, result, self.scanner_checks)

    def run_structural_gap_analysis(
        self,
        request: StructuralGapRequest,
        *,
        walking_skeleton_runner: SkeletonRunner | None = None,
    ) -> StructuralGapOutcome:
        """Run the host structural workflow before accepting Planning."""
        return self.gap_analyzer.evaluate(request, walking_skeleton_runner=walking_skeleton_runner)

    def complete_final_stage(
        self,
        task_id: str,
        run_id: str,
        completion_receipt_ref: ReceiptRef | None,
        todo_ref: ArtifactRef | None,
    ) -> TaskState:
        """Complete Build only after independent verification and assigned work pass."""
        checkpoint = self.checkpoint_store.load_checkpoint(task_id)
        if checkpoint is None:
            raise TransitionError("task has no checkpoint")
        revision, state_dict, _ = checkpoint
        state = TaskState(**state_dict)
        if state.run_id != run_id or state.task_id != task_id:
            raise TransitionError("final stage task/run mismatch")
        if state.current_stage is not Stage.BUILD or Stage.BUILD in state.completed_stages:
            raise TransitionError("task is not at an unfinished Build stage")
        receipt_artifact = self._verify_stage_receipt(state, completion_receipt_ref)
        self._verify_final_build_evidence(state, receipt_artifact)
        if todo_ref is None:
            raise TransitionError("completed final-stage work list required")
        if state.active_work_artifact_id != todo_ref.artifact_id:
            raise TransitionError("final work list does not match host assignment")
        try:
            self.work_todos.require_complete(todo_ref, task_id=task_id, run_id=run_id, stage=state.current_stage.value)
        except WorkTodoError as exc:
            raise TransitionError(f"invalid or unfinished final work list: {exc}") from exc
        self._verify_stage_evidence(receipt_artifact, todo_ref)
        completed = state.model_copy(
            update={
                "completed_stages": (*state.completed_stages, Stage.BUILD),
                "active_work_artifact_id": None,
            }
        )
        try:
            self.checkpoint_store.checkpoint_cas(task_id, revision, completed.model_dump(mode="json"))
        except CompetingWriterError as exc:
            raise TransitionError(f"final stage checkpoint CAS failed: {exc}") from exc
        self.event_store.append(
            task_id,
            "stage_completed",
            Stage.BUILD.value,
            event_id=f"stage-completed:{task_id}:{run_id}:{revision + 1}",
        )
        return completed

    def route_validation_rework(self, task_id: str, run_id: str, validation_ref: ArtifactRef) -> ArtifactRef:
        """Return failed verifier observations to a new Planning revision."""
        from agent.contracts.build_validation import BuildValidationRecord, PlanningReworkInput

        checkpoint = self.checkpoint_store.load_checkpoint(task_id)
        if checkpoint is None:
            raise TransitionError("task has no checkpoint for validation rework")
        revision, state_dict, _ = checkpoint
        state = TaskState(**state_dict)
        if (state.task_id, state.run_id) != (task_id, run_id) or state.current_stage is not Stage.BUILD:
            raise TransitionError("validation rework requires an active Build task")
        if Stage.BUILD in state.completed_stages:
            raise TransitionError("completed Build cannot be routed to Planning")
        if validation_ref.contract_id != "build_validation_record":
            raise TransitionError("wrong validation record contract")
        if (
            state.build_verification_artifact_id != validation_ref.artifact_id
            or state.build_verification_digest != validation_ref.artifact_digest
        ):
            raise TransitionError("validation record was not received from the host-dispatched verifier")
        if (
            self.artifact_store.get_digest(validation_ref.artifact_id, validation_ref.artifact_revision)
            != validation_ref.artifact_digest
        ):
            raise TransitionError("validation record digest mismatch")
        record = BuildValidationRecord.model_validate_json(
            self.artifact_store.get_verified(validation_ref.artifact_id, validation_ref.artifact_revision)
        )
        if (record.task_id, record.run_id) != (task_id, run_id):
            raise TransitionError("validation record belongs to another task or run")
        issues = record.planning_issue_inputs()
        if not issues:
            raise TransitionError("no failed validation observations for Planning")
        next_revision = state.planning_revision + 1
        rework = PlanningReworkInput(
            task_id=task_id,
            run_id=run_id,
            planning_revision=next_revision,
            validation_ref=validation_ref,
            issue_sources=issues,
        )
        artifact_id = f"planning-rework:{task_id}:{run_id}:{next_revision}"
        digest = self.artifact_store.put_immutable(rework, artifact_id, 1, "planning_rework_input", "1.0")
        updated = state.model_copy(
            update={
                "current_stage": Stage.PLANNING,
                "completed_stages": tuple(
                    stage for stage in state.completed_stages if stage in {Stage.RESEARCH, Stage.AUDIT_DISCOVERY}
                ),
                "active_work_artifact_id": None,
                "build_verification_artifact_id": None,
                "build_verification_digest": None,
                "planning_revision": next_revision,
            }
        )
        try:
            self.checkpoint_store.checkpoint_cas(task_id, revision, updated.model_dump(mode="json"))
        except CompetingWriterError as exc:
            raise TransitionError("validation rework checkpoint conflict") from exc
        self.event_store.append(
            task_id,
            "validation_rework_requested",
            artifact_id,
            event_id=f"validation-rework:{task_id}:{run_id}:{next_revision}",
        )
        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_revision=1,
            artifact_digest=digest,
            contract_id="planning_rework_input",
            contract_version="1.0",
            serializer_profile=SERIALIZER_PROFILE,
        )

    def _verify_final_build_evidence(self, state: TaskState, artifact: ArtifactRef) -> None:
        """Require a passing independent verifier record bound to an actual Build record."""
        from agent.contracts.build import BuildRecord
        from agent.contracts.build_validation import BuildValidationRecord, CriterionResult

        try:
            raw = self.artifact_store.get_verified(artifact.artifact_id, artifact.artifact_revision)
            verification = BuildValidationRecord.model_validate_json(raw)
            if (verification.task_id, verification.run_id) != (state.task_id, state.run_id):
                raise ValueError("verification belongs to another task or run")
            if (
                state.build_verification_artifact_id != artifact.artifact_id
                or state.build_verification_digest != artifact.artifact_digest
            ):
                raise ValueError("verification was not received from the host-dispatched verifier")
            if not verification.criterion_results or not verification.e2e_results:
                raise ValueError("independent verification observations required")
            if any(item.outcome is not CriterionResult.VALID for item in verification.criterion_results):
                raise ValueError("acceptance criterion did not pass")
            if any(
                item.outcome is not CriterionResult.VALID or item.exit_code != 0 for item in verification.e2e_results
            ):
                raise ValueError("end-to-end verification did not pass")
            build_ref = verification.build_ref
            if build_ref.contract_id != "build_record":
                raise ValueError("verification does not cite a Build record")
            if (
                self.artifact_store.get_digest(build_ref.artifact_id, build_ref.artifact_revision)
                != build_ref.artifact_digest
            ):
                raise ValueError("Build record digest mismatch")
            build = BuildRecord.model_validate_json(
                self.artifact_store.get_verified(build_ref.artifact_id, build_ref.artifact_revision)
            )
            if (build.task_id, build.run_id) != (state.task_id, state.run_id):
                raise ValueError("Build record belongs to another task or run")
        except Exception as exc:
            raise TransitionError("final Build requires passing independent verification evidence") from exc

    def _declared_dispatch_role(self, stage: Stage, requested_role: str | None = None) -> str:
        """Resolve the single workflow-owned stage role, rejecting missing configuration."""
        config_path = Path(__file__).resolve().parents[2] / ".agents" / "contracts" / "workflow.yaml"
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            bundle = config["bundle"]
            declared = config["role_workflows"][stage.value]
            workflow = declared["workflow"]
            if stage is Stage.BUILD and requested_role == "build_verifier":
                workflow = workflow["independent_verification"]["workflow"]
            role = workflow["role_id"]
            stage_id = workflow["stage_id"]
        except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
            raise TransitionError("registered workflow role unavailable") from exc
        if bundle.get("transition_owner") != "host_controller" or stage_id != stage.value or not isinstance(role, str):
            raise TransitionError("workflow dispatch ownership or stage mismatch")
        return role

    @staticmethod
    def _dispatch_ref(envelope: HostDispatchEnvelope, digest: str) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=f"agent-dispatch:{envelope.request_id}",
            artifact_revision=envelope.request_revision,
            artifact_digest=digest,
            contract_id="host_dispatch_envelope",
            contract_version="1.0",
            serializer_profile=SERIALIZER_PROFILE,
        )

    def prepare_agent_dispatch(
        self,
        task_id: str,
        input_request_ref: ArtifactRef,
        information_needed: str,
        *,
        requested_role: str | None = None,
        requester_role: str = "workflow_entry",
        action: str | None = None,
        expected_result: str | None = None,
    ) -> tuple[HostDispatchEnvelope, ArtifactRef, ArtifactRef]:
        """Allocate and persist the exact host route before any agent can run.

        Do not accept agent-supplied identity fields or a caller-defined return target.
        """
        state = self.get_state(task_id)
        if state is None or not information_needed.strip():
            raise TransitionError("dispatch requires an initialized task and nonempty objective")
        stage = state.current_stage
        role = self._declared_dispatch_role(stage, requested_role)
        if requested_role is not None and requested_role != role:
            self.event_store.append(
                task_id, "agent_dispatch_rejected", f"stage={stage.value};requested={requested_role};allowed={role}"
            )
            raise TransitionError("incorrect agent role for active workflow stage")
        if stage is Stage.RESEARCH:
            if requester_role not in {"workflow_entry", "audit_discovery", "planning"}:
                raise TransitionError("Research requester is not authorized")
            respond_to = requester_role
        else:
            if requester_role != "workflow_entry":
                raise TransitionError("stage result must return to the host")
            respond_to = "host_controller"
        if input_request_ref.artifact_revision < 1 or (
            self.artifact_store.get_digest(input_request_ref.artifact_id, input_request_ref.artifact_revision)
            != input_request_ref.artifact_digest
        ):
            raise TransitionError("dispatch input artifact revision or digest mismatch")
        try:
            self.artifact_store.get_verified(input_request_ref.artifact_id, input_request_ref.artifact_revision)
        except Exception as exc:
            raise TransitionError("dispatch input is not verified") from exc
        fingerprint = sha256(
            (
                f"{task_id}:{state.run_id}:{stage.value}:"
                f"{'build_verifier:' if role == 'build_verifier' else ''}"
                f"{input_request_ref.artifact_id}:{input_request_ref.artifact_revision}:"
                f"{input_request_ref.artifact_digest}:{information_needed.strip()}"
            ).encode()
        ).hexdigest()[:24]
        request_id = (
            f"research-{task_id}" if stage is Stage.RESEARCH and len(task_id) <= 119 else f"dispatch-{fingerprint}"
        )
        envelope = HostDispatchEnvelope(
            task_id=task_id,
            run_id=state.run_id,
            stage=stage.value,
            role=role,
            request_id=request_id,
            request_revision=input_request_ref.artifact_revision,
            respond_to=respond_to,
            requester_role=requester_role,
            input_request_ref=input_request_ref,
            information_needed=information_needed.strip(),
        )
        aid = f"agent-dispatch:{request_id}"
        try:
            digest = self.artifact_store.put_immutable(
                envelope, aid, envelope.request_revision, "host_dispatch_envelope", "1.0"
            )
        except Exception as exc:
            raise TransitionError("conflicting or unpersisted host dispatch identity") from exc
        binding = WorkBinding(
            task_id=envelope.task_id,
            run_id=envelope.run_id,
            stage=stage.value,
            request_id=envelope.request_id,
            request_revision=envelope.request_revision,
            input_request_ref=envelope.input_request_ref,
        )
        _work, todo_ref = self.assign_work(
            binding,
            action=action or information_needed.strip(),
            expected_result=expected_result or f"Verified {role} output persisted by host",
        )
        self.event_store.append(
            task_id,
            "agent_dispatch_prepared",
            f"{stage.value}:{role}:{request_id}",
            event_id=f"dispatch:{task_id}:{state.run_id}:{request_id}",
        )
        return envelope, self._dispatch_ref(envelope, digest), todo_ref

    def verify_agent_dispatch(self, envelope: HostDispatchEnvelope) -> None:
        """Fail closed on substituted, stale or wrongly staged dispatch requests."""
        state = self.get_state(envelope.task_id)
        if state is None or state.run_id != envelope.run_id or state.current_stage.value != envelope.stage:
            raise TransitionError("stale or mismatched agent dispatch stage identity")
        if self._declared_dispatch_role(state.current_stage, envelope.role) != envelope.role:
            raise TransitionError("agent dispatch targets unauthorized role")
        aid = f"agent-dispatch:{envelope.request_id}"
        try:
            raw = self.artifact_store.get_verified(aid, envelope.request_revision)
            stored = HostDispatchEnvelope.model_validate_json(raw)
        except Exception as exc:
            raise TransitionError("host dispatch envelope is missing or unverified") from exc
        if stored != envelope:
            raise TransitionError("agent dispatch differs from persisted host assignment")
        if state.current_stage is Stage.RESEARCH:
            if envelope.respond_to != envelope.requester_role or envelope.respond_to not in {
                "workflow_entry",
                "audit_discovery",
                "planning",
            }:
                raise TransitionError("invalid Research respond_to binding")
        elif envelope.respond_to != "host_controller":
            raise TransitionError("invalid host return route")
        if (
            self.artifact_store.get_digest(
                envelope.input_request_ref.artifact_id, envelope.input_request_ref.artifact_revision
            )
            != envelope.input_request_ref.artifact_digest
        ):
            raise TransitionError("stale or changed dispatch input")

    def receive_agent_result(self, envelope: HostDispatchEnvelope, result: HostDispatchResult) -> ArtifactRef:
        """Receive an agent result at the host-controlled route, not at another agent."""
        self.verify_agent_dispatch(envelope)
        for field in ("task_id", "run_id", "stage", "role", "request_id", "request_revision", "respond_to"):
            if getattr(result, field) != getattr(envelope, field):
                raise TransitionError(f"agent result routing mismatch: {field}")
        output = result.output_ref
        if self.artifact_store.get_digest(output.artifact_id, output.artifact_revision) != output.artifact_digest:
            raise TransitionError("agent result output artifact digest mismatch")
        try:
            raw = self.artifact_store.get_verified(output.artifact_id, output.artifact_revision)
            from agent.contracts.audit_discovery import AuditDiscoveryPackage
            from agent.contracts.build import BuildRecord
            from agent.contracts.build_validation import BuildValidationRecord
            from agent.contracts.fixture_validation import FixtureValidationRecord
            from agent.contracts.planning import PlanningRecord
            from agent.contracts.research import ResearchRecord

            contracts: dict[Stage, tuple[str, type[BaseModel]]] = {
                Stage.RESEARCH: ("research_record", ResearchRecord),
                Stage.AUDIT_DISCOVERY: ("audit_discovery_package", AuditDiscoveryPackage),
                Stage.PLANNING: ("planning_record", PlanningRecord),
                Stage.FIXTURE_VALIDATION: ("fixture_validation_record", FixtureValidationRecord),
                Stage.BUILD: ("build_record", BuildRecord),
            }
            required_contract, contract_model = (
                ("build_validation_record", BuildValidationRecord)
                if envelope.stage == Stage.BUILD.value and envelope.role == "build_verifier"
                else contracts[Stage(envelope.stage)]
            )
            if output.contract_id != required_contract:
                raise ValueError("agent result contract belongs to another stage")
            verified_record = contract_model.model_validate_json(raw)
            if (getattr(verified_record, "task_id", None), getattr(verified_record, "run_id", None)) != (
                envelope.task_id,
                envelope.run_id,
            ):
                raise ValueError("agent result task/run identity mismatch")
            if Stage(envelope.stage) is Stage.BUILD and envelope.role == "builder":
                from agent.contracts.host import BuildAdmissionReceipt, PackageLockReceipt, admission_receipt_subject

                build = BuildRecord.model_validate(verified_record)
                admission_bytes = self.artifact_store.get_verified(
                    build.admission_ref.artifact_id, build.admission_ref.artifact_revision
                )
                lock_bytes = self.artifact_store.get_verified(
                    build.lock_ref.artifact_id, build.lock_ref.artifact_revision
                )
                if (
                    self.artifact_store.get_digest(
                        build.admission_ref.artifact_id, build.admission_ref.artifact_revision
                    )
                    != build.admission_ref.artifact_digest
                    or self.artifact_store.get_digest(build.lock_ref.artifact_id, build.lock_ref.artifact_revision)
                    != build.lock_ref.artifact_digest
                ):
                    raise ValueError("Build admission or package lock digest mismatch")
                admission = BuildAdmissionReceipt.model_validate_json(admission_bytes)
                locked = PackageLockReceipt.model_validate_json(lock_bytes)
                if admission.lock_receipt_ref != locked.receipt_ref:
                    raise ValueError("Build admission not bound to package lock")
                subject = admission_receipt_subject(
                    admission.lock_receipt_ref,
                    admission.authorized_action_ids,
                    admission.authorized_tool_ids,
                    admission.tool_registry_ref,
                    admission.recovery_readiness_ref,
                )
                if not self.receipt_store.verify(
                    admission.receipt_ref.receipt_id, admission.receipt_ref.receipt_digest, subject
                ):
                    raise ValueError("untrusted Build admission receipt")
                if any(action.action_id not in admission.authorized_action_ids for action in build.action_executions):
                    raise ValueError("Build result contains unadmitted actions")
        except Exception as exc:
            raise TransitionError("agent result output contract or admission is not verified") from exc
        aid = f"agent-dispatch-result:{envelope.request_id}"
        try:
            digest = self.artifact_store.put_immutable(
                result, aid, envelope.request_revision, "host_dispatch_result", "1.0"
            )
        except Exception as exc:
            raise TransitionError("agent return is conflicting or unpersisted") from exc
        self.event_store.append(
            envelope.task_id,
            "agent_result_received",
            f"{envelope.respond_to}:{aid}",
            event_id=f"agent-result:{envelope.task_id}:{envelope.request_id}:{aid}",
        )
        if envelope.stage == Stage.BUILD.value and envelope.role == "build_verifier":
            checkpoint = self.checkpoint_store.load_checkpoint(envelope.task_id)
            if checkpoint is None:
                raise TransitionError("verifier result has no active checkpoint")
            revision, state_dict, _ = checkpoint
            state = TaskState(**state_dict)
            if state.current_stage is not Stage.BUILD or Stage.BUILD in state.completed_stages:
                raise TransitionError("verifier result arrived outside active Build")
            updated = state.model_copy(
                update={
                    "build_verification_artifact_id": output.artifact_id,
                    "build_verification_digest": output.artifact_digest,
                }
            )
            try:
                self.checkpoint_store.checkpoint_cas(envelope.task_id, revision, updated.model_dump(mode="json"))
            except CompetingWriterError as exc:
                raise TransitionError(f"verifier result checkpoint conflict: {exc}") from exc
        return ArtifactRef(
            artifact_id=aid,
            artifact_revision=envelope.request_revision,
            artifact_digest=digest,
            contract_id="host_dispatch_result",
            contract_version="1.0",
            serializer_profile=SERIALIZER_PROFILE,
        )

    def assign_work(
        self,
        binding: WorkBinding,
        *,
        action: str | None = None,
        expected_result: str | None = None,
        work_plan_ref: ArtifactRef | None = None,
    ) -> tuple[TodoList, ArtifactRef]:
        """Host registers a stage assignment and auto-generates its work tracker."""
        checkpoint = self.checkpoint_store.load_checkpoint(binding.task_id)
        if checkpoint is None:
            raise TransitionError("cannot assign work before task initialization")
        revision, state_dict, _ = checkpoint
        state = TaskState(**state_dict)
        if state.run_id != binding.run_id or state.current_stage.value != binding.stage:
            raise TransitionError("work assignment belongs to a different task stage or run")
        if state.current_stage in state.completed_stages:
            raise TransitionError("cannot assign work after stage completion")
        work_id = WorkTodoManager._identity(binding, "work-todo")
        if state.active_work_artifact_id is not None and state.active_work_artifact_id != work_id:
            raise TransitionError("different work request already assigned to this stage")
        record, ref = self.work_todos.start(
            binding, action=action, expected_result=expected_result, work_plan_ref=work_plan_ref
        )
        if state.active_work_artifact_id is None:
            updated = state.model_copy(update={"active_work_artifact_id": ref.artifact_id})
            try:
                self.checkpoint_store.checkpoint_cas(binding.task_id, revision, updated.model_dump(mode="json"))
            except CompetingWriterError as exc:
                raise TransitionError(f"concurrent work assignment: {exc}") from exc
            self.event_store.append(
                binding.task_id,
                "work_assigned",
                ref.artifact_id,
                event_id=f"work-assigned:{binding.task_id}:{ref.artifact_id}:{ref.artifact_revision}",
            )
        return record, ref

    def finish_capability_work(
        self,
        task_id: str,
        run_id: str,
        stage: Stage,
        todo_ref: ArtifactRef,
    ) -> TaskState:
        """Finish verified role-local work without issuing a stage receipt or advancing."""
        checkpoint = self.checkpoint_store.load_checkpoint(task_id)
        if checkpoint is None:
            raise TransitionError("capability work has no checkpoint")
        revision, state_dict, _ = checkpoint
        state = TaskState(**state_dict)
        if (state.task_id, state.run_id, state.current_stage) != (task_id, run_id, stage):
            raise TransitionError("capability work stage/task/run mismatch")
        if state.active_work_artifact_id != todo_ref.artifact_id:
            raise TransitionError("capability work does not match assigned request")
        try:
            self.work_todos.require_complete(todo_ref, task_id=task_id, run_id=run_id, stage=stage.value)
        except WorkTodoError as exc:
            raise TransitionError(f"capability work not verified: {exc}") from exc
        updated = state.model_copy(update={"active_work_artifact_id": None})
        try:
            self.checkpoint_store.checkpoint_cas(task_id, revision, updated.model_dump(mode="json"))
        except CompetingWriterError as exc:
            raise TransitionError(f"capability work checkpoint conflict: {exc}") from exc
        self.event_store.append(
            task_id,
            "capability_work_completed",
            todo_ref.artifact_id,
            event_id=f"capability-work-completed:{task_id}:{todo_ref.artifact_id}:{todo_ref.artifact_revision}",
        )
        return updated

    def get_state(self, task_id: str) -> TaskState | None:
        """Get current task state from checkpoint."""
        checkpoint = self.checkpoint_store.load_checkpoint(task_id)
        if checkpoint is None:
            return None
        _, state_dict, _ = checkpoint
        return TaskState(**state_dict)

    def init_task(self, task_id: str, run_id: str) -> TaskState:
        """Initialize a new task."""
        state = TaskState(task_id=task_id, run_id=run_id)
        self.checkpoint_store.checkpoint_cas(task_id, 0, state.model_dump(mode="json"))
        self.event_store.append(task_id, "task_init", f"run_id={run_id}", event_id=f"task-init:{task_id}:{run_id}")
        return state

    def issue_stage_receipt(
        self,
        stage: Stage,
        task_id: str = "",
        run_id: str = "",
        revision: int = 0,
        artifact_digest: str = "",
        artifact_id: str = "",
    ) -> ReceiptRef:
        """Issue an artifact-bound receipt from verified host evidence.

        Without an explicit result artifact, bind the latest assigned work-list
        revision. The work-list must be verified during stage transition.
        """
        if not task_id or not run_id:
            raise TransitionError("stage receipt requires task/run identity")
        state = self.get_state(task_id)
        if state is None or state.run_id != run_id or state.current_stage != stage:
            raise TransitionError("stage receipt must belong to active host task")
        if not artifact_id:
            if state.active_work_artifact_id is None:
                raise TransitionError("stage receipt requires assigned artifact evidence")
            artifact_id = state.active_work_artifact_id
            revision = self.artifact_store.latest_revision(artifact_id)
            artifact_digest = self.artifact_store.get_digest(artifact_id, revision) or ""
        if revision < 1 or len(artifact_digest) != 64:
            raise TransitionError("stage receipt requires complete artifact identity")
        try:
            if self.artifact_store.get_digest(artifact_id, revision) != artifact_digest:
                raise ValueError("artifact digest mismatch")
            self.artifact_store.get_verified(artifact_id, revision)
        except Exception as exc:
            raise TransitionError("stage receipt artifact is not verified") from exc
        subject = f"stage_complete:{task_id}:{run_id}:{stage.value}:{artifact_id}:{revision}:{artifact_digest}"
        receipt_id = f"receipt-{task_id}-{stage.value}-{artifact_digest[:16]}"
        _, receipt_digest = self.receipt_store.issue_verified(receipt_id, "host", subject)
        return ReceiptRef(
            receipt_id=receipt_id,
            receipt_digest=receipt_digest,
            issuer_id="host",
        )

"""Effect executor — sole producer of physical Build effects."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from agent.contracts.build import BuildActionExecution, BuildActionStatus
from agent.contracts.build_schedule import BuildWave, VerifiedWaveResult
from agent.contracts.host import BuildAdmissionReceipt, admission_receipt_subject
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.authorization import AuthorizationEngine, AuthorizationError
from agent.runtime.checkpoint_store import CheckpointStore
from agent.runtime.receipt_store import ReceiptStore


class EffectExecutionError(Exception):
    pass


def _is_within(child: Path, parent: Path) -> bool:
    """Check that *child* is contained within *parent* using real paths.

    Uses os.path.realpath to resolve symlinks before comparison,
    preventing sibling-path confusion and symlink races.
    """
    real_child = Path(os.path.realpath(str(child)))
    real_parent = Path(os.path.realpath(str(parent)))
    try:
        real_child.relative_to(real_parent)
        return True
    except ValueError:
        return False


class EffectExecutor:
    """Sole host effect owner for physical build operations.

    - Rechecks preconditions at effect time.
    - Writes durable PRE_EFFECT checkpoints before mutation.
    - Uses atomic writes (temp file + rename) to prevent partial effects.
    - Captures actual effects with pre/post digests.
    - Reconciles uncertain effects after crash.
    - Issues POST_EFFECT_RECONCILED receipts on successful reconciliation.
    """

    def __init__(
        self,
        authorization: AuthorizationEngine,
        checkpoint_store: CheckpointStore,
        receipt_store: ReceiptStore,
        workspace_root: str | Path,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._auth = authorization
        self._checkpoints = checkpoint_store
        self._receipts = receipt_store
        self._artifacts = artifact_store
        self._workspace = Path(os.path.realpath(str(workspace_root)))
        self._workspace.mkdir(parents=True, exist_ok=True)

    def _check_containment(self, path: str, action_id: str) -> str | None:
        """Resolve path relative to workspace, check containment with realpath.

        Returns the resolved absolute path if safe, or None if the path
        escapes the workspace (including via symlinks).
        """
        candidate = Path(path) if Path(path).is_absolute() else self._workspace / path

        # realpath resolves existing ancestors and lexical remainder without
        # creating directories before the containment and authorization gates.
        real_candidate = Path(os.path.realpath(str(candidate)))

        if not _is_within(real_candidate, self._workspace):
            return None

        # Double-check with authorization engine
        try:
            self._auth.check_path_safety(str(real_candidate))
        except AuthorizationError:
            return None

        return str(real_candidate)

    def _write_atomic(self, path: Path, content: str) -> None:
        """Write content atomically: write to temp file, then rename."""
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=".oneshot-tmp-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.replace(tmp_name, str(path))
        except Exception:
            # Clean up temp file on failure
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    def _pre_effect_checkpoint(
        self,
        action_id: str,
        file_path: str,
        expected_pre: str | None,
        expected_post: str | None,
        target_path: str | None = None,
    ) -> None:
        """Write a durable pre-effect checkpoint to the checkpoint store."""
        checkpoint_data = {
            "type": "pre_effect",
            "action_id": action_id,
            "file_path": file_path,
            "expected_pre_digest": expected_pre,
            "expected_post_digest": expected_post,
            "target_path": target_path,
        }
        self._checkpoints.checkpoint_cas(
            f"pre-effect-{action_id}",
            0,
            checkpoint_data,
        )

    def _clear_pre_effect_checkpoint(self, action_id: str) -> None:
        """Mark pre-effect checkpoint as completed by writing a completion record."""
        completion_data = {
            "type": "post_effect",
            "action_id": action_id,
            "status": "completed",
        }
        self._checkpoints.checkpoint_cas(
            f"pre-effect-{action_id}",
            1,
            completion_data,
        )

    def _has_pre_effect_checkpoint(self, action_id: str) -> dict[str, object] | None:
        """Check if a pre-effect checkpoint exists and is not yet completed."""
        checkpoint = self._checkpoints.load_checkpoint(f"pre-effect-{action_id}")
        if checkpoint is None:
            return None
        _, state_dict, _ = checkpoint
        if isinstance(state_dict, dict) and state_dict.get("type") == "pre_effect":
            return state_dict
        return None

    def execute_admitted(
        self,
        action_id: str,
        action_kind: str,
        admission_receipt: BuildAdmissionReceipt,
        target_path: str | None = None,
        source_path: str | None = None,
        content: str | None = None,
        expected_source_digest: str | None = None,
        wave: BuildWave | None = None,
    ) -> BuildActionExecution:
        """Execute a single admitted build action.

        Requires a valid BuildAdmissionReceipt — no action may proceed
        without host-issued admission. Writes a durable pre-effect checkpoint
        before mutation, uses atomic writes, and clears the checkpoint
        after successful completion.
        """
        # Verify admission — required, not optional
        if action_id not in admission_receipt.authorized_action_ids:
            raise EffectExecutionError(
                f"action {action_id} not authorized by admission {admission_receipt.admission_id}"
            )

        # Verify the admission receipt itself is valid
        if not self._receipts.verify(
            admission_receipt.receipt_ref.receipt_id,
            admission_receipt.receipt_ref.receipt_digest,
            admission_receipt_subject(
                admission_receipt.lock_receipt_ref,
                admission_receipt.authorized_action_ids,
                admission_receipt.authorized_tool_ids,
                admission_receipt.tool_registry_ref,
                admission_receipt.recovery_readiness_ref,
            ),
        ):
            raise EffectExecutionError(f"invalid admission receipt for action {action_id}")

        # Verify admission receipt issuer is trusted
        if admission_receipt.receipt_ref.issuer_id != "host":
            raise EffectExecutionError(f"untrusted admission issuer: {admission_receipt.receipt_ref.issuer_id}")

        # Execution-time filesystem containment with symlink resolution
        resolved_target: str | None = None
        resolved_source: str | None = None
        if target_path:
            resolved_target = self._check_containment(target_path, action_id)
            if resolved_target is None:
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.BLOCKED,
                    error=f"path escapes workspace (containment check failed): {target_path}",
                )
        if source_path:
            resolved_source = self._check_containment(source_path, action_id)
            if resolved_source is None:
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.BLOCKED,
                    error=f"path escapes workspace (containment check failed): {source_path}",
                )

        if wave is not None:
            if wave.wave_index > 1:
                previous = wave.previous_wave_result_ref
                prior_receipt = wave.previous_wave_receipt_ref
                if (
                    previous is None
                    or prior_receipt is None
                    or self._artifacts is None
                    or self._artifacts.get_digest(previous.artifact_id, previous.artifact_revision)
                    != previous.artifact_digest
                ):
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.BLOCKED,
                        error="previous wave result is not verified",
                    )
                try:
                    prior = VerifiedWaveResult.model_validate_json(
                        self._artifacts.get_verified(previous.artifact_id, previous.artifact_revision)
                    )
                except Exception:
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.BLOCKED,
                        error="previous wave result cannot be reopened",
                    )
                if (
                    not prior.accepted
                    or prior_receipt.issuer_id != "host"
                    or not self._receipts.verify(
                        prior_receipt.receipt_id,
                        prior_receipt.receipt_digest,
                        f"verified_wave:{previous.artifact_digest}",
                    )
                    or any(
                        path not in prior.output_digests or prior.output_digests[path] != digest
                        for path, digest in wave.expected_preimages.items()
                    )
                ):
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.BLOCKED,
                        error="previous wave acceptance or preimage pins are invalid",
                    )
            action_paths = {
                path
                for batch in wave.batches
                for task in batch.tasks
                if action_id in task.todo.source_action_ids
                for path in task.todo.authorized_paths
            }
            observed: dict[str, str | None] = {}
            for path in action_paths:
                resolved = self._check_containment(path, action_id)
                if resolved is None:
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.BLOCKED,
                        error="wave path escaped workspace",
                    )
                file = Path(resolved)
                if os.path.lexists(file) and not file.is_file():
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.BLOCKED,
                        error="wave preimage is not a regular file",
                    )
                observed[path] = hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None
            try:
                wave.require_action_preimages(action_id, observed)
            except ValueError as exc:
                return BuildActionExecution(action_id=action_id, status=BuildActionStatus.BLOCKED, error=str(exc))

        try:
            if action_kind == "create" and target_path and content is not None:
                full_path = Path(resolved_target)  # type: ignore[arg-type]
                full_path.parent.mkdir(parents=True, exist_ok=True)
                pre_digest = None
                if full_path.exists():
                    pre_digest = hashlib.sha256(full_path.read_bytes()).hexdigest()

                # Durable pre-effect checkpoint
                expected_post = hashlib.sha256(content.encode()).hexdigest()
                self._pre_effect_checkpoint(action_id, target_path, pre_digest, expected_post)

                # Atomic write
                self._write_atomic(full_path, content)
                post_digest = hashlib.sha256(full_path.read_bytes()).hexdigest()

                # Clear pre-effect checkpoint — effect completed
                self._clear_pre_effect_checkpoint(action_id)

                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.COMPLETED,
                    pre_image_digest=pre_digest,
                    post_image_digest=post_digest,
                )

            elif action_kind == "modify" and source_path and content is not None:
                full_path = Path(resolved_source)  # type: ignore[arg-type]
                if not full_path.exists():
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.FAILED,
                        error=f"source file not found: {source_path}",
                    )
                pre_digest = hashlib.sha256(full_path.read_bytes()).hexdigest()
                if expected_source_digest and pre_digest != expected_source_digest:
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.FAILED,
                        error=f"preimage mismatch: expected {expected_source_digest}, got {pre_digest}",
                    )

                expected_post = hashlib.sha256(content.encode()).hexdigest()
                self._pre_effect_checkpoint(action_id, source_path, pre_digest, expected_post)

                self._write_atomic(full_path, content)
                post_digest = hashlib.sha256(full_path.read_bytes()).hexdigest()

                self._clear_pre_effect_checkpoint(action_id)

                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.COMPLETED,
                    pre_image_digest=pre_digest,
                    post_image_digest=post_digest,
                )

            elif action_kind == "move" and source_path and target_path:
                source = Path(resolved_source)  # type: ignore[arg-type]
                target = Path(resolved_target)  # type: ignore[arg-type]
                if source == target or not source.is_file() or source.is_symlink() or os.path.lexists(target):
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.FAILED,
                        error="move requires a regular source and absent distinct destination",
                    )
                pre_digest = hashlib.sha256(source.read_bytes()).hexdigest()
                if expected_source_digest is None or pre_digest != expected_source_digest:
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.FAILED,
                        error="move source preimage mismatch or missing expected digest",
                    )
                self._pre_effect_checkpoint(action_id, source_path, pre_digest, pre_digest, target_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                if os.path.lexists(target):
                    raise EffectExecutionError("move destination changed before effect")
                os.replace(source, target)
                self._clear_pre_effect_checkpoint(action_id)
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.COMPLETED,
                    pre_image_digest=pre_digest,
                    post_image_digest=pre_digest,
                )

            elif action_kind == "remove" and source_path:
                full_path = Path(resolved_source)  # type: ignore[arg-type]
                if not full_path.exists():
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.FAILED,
                        error=f"source file not found: {source_path}",
                    )
                pre_digest = hashlib.sha256(full_path.read_bytes()).hexdigest()
                if expected_source_digest and pre_digest != expected_source_digest:
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.FAILED,
                        error=f"preimage mismatch: expected {expected_source_digest}, got {pre_digest}",
                    )

                self._pre_effect_checkpoint(action_id, source_path, pre_digest, None)

                full_path.unlink()

                self._clear_pre_effect_checkpoint(action_id)

                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.COMPLETED,
                    pre_image_digest=pre_digest,
                )

            else:
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.BLOCKED,
                    error=f"unsupported action: kind={action_kind} target={target_path} source={source_path}",
                )

        except Exception as e:
            # Check if pre-effect checkpoint exists — effect may be uncertain
            if self._has_pre_effect_checkpoint(action_id):
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.EFFECT_UNCERTAIN,
                    error=f"effect may have partially applied: {e}",
                )
            return BuildActionExecution(
                action_id=action_id,
                status=BuildActionStatus.FAILED,
                error=str(e),
            )

    def reconcile_effect(
        self,
        action_id: str,
        file_path: str,
        expected_post_digest: str | None,
    ) -> BuildActionExecution:
        """Reconcile an uncertain effect after crash or interruption.

        Checks the durable pre-effect checkpoint to determine if the
        effect was in progress when the crash occurred. Compares actual
        file state against expected post-effect digest.

        Returns:
        - COMPLETED if the file matches the expected post-effect digest
        - EFFECT_UNCERTAIN if a pre-effect checkpoint exists but file
          state cannot be confirmed
        - FAILED if the file is missing or digest mismatch confirms
          the effect did not complete
        """
        # Check for durable pre-effect checkpoint
        pre_checkpoint = self._has_pre_effect_checkpoint(action_id)
        if pre_checkpoint is not None:
            move_target = pre_checkpoint.get("target_path")
            if isinstance(move_target, str) and move_target:
                source = self._check_containment(str(pre_checkpoint["file_path"]), action_id)
                target = self._check_containment(move_target, action_id)
                if source is None or target is None:
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.EFFECT_UNCERTAIN,
                        error="move path no longer satisfies containment",
                    )
                source_file, target_file = Path(source), Path(target)
                expected = pre_checkpoint.get("expected_post_digest")
                if not source_file.exists() and target_file.is_file():
                    actual = hashlib.sha256(target_file.read_bytes()).hexdigest()
                    if actual == expected:
                        self._clear_pre_effect_checkpoint(action_id)
                        self._receipts.issue_verified(
                            f"reconciled-{action_id}", "host", f"post_effect_reconciled:{action_id}:{actual}"
                        )
                        return BuildActionExecution(
                            action_id=action_id,
                            status=BuildActionStatus.COMPLETED,
                            pre_image_digest=actual,
                            post_image_digest=actual,
                        )
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.EFFECT_UNCERTAIN,
                    error="move destination/source state cannot be confirmed after crash",
                )
            # A crash occurred during this effect
            full_path = Path(os.path.realpath(str(self._workspace / file_path)))
            if not full_path.exists():
                if expected_post_digest is None:
                    # Remove action completed before crash
                    self._clear_pre_effect_checkpoint(action_id)
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.COMPLETED,
                    )
                # File missing but expected to exist — effect uncertain
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.EFFECT_UNCERTAIN,
                    error=f"file missing after crash with pre-effect checkpoint: {file_path}",
                )

            actual_digest = hashlib.sha256(full_path.read_bytes()).hexdigest()
            if expected_post_digest is not None:
                if actual_digest == expected_post_digest:
                    # Effect completed before crash — reconcile
                    self._clear_pre_effect_checkpoint(action_id)
                    # Issue POST_EFFECT_RECONCILED receipt
                    self._receipts.issue_verified(
                        f"reconciled-{action_id}",
                        "host",
                        f"post_effect_reconciled:{action_id}:{actual_digest}",
                    )
                    return BuildActionExecution(
                        action_id=action_id,
                        status=BuildActionStatus.COMPLETED,
                        post_image_digest=actual_digest,
                    )
                # Digest mismatch — effect was interrupted mid-write
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.EFFECT_UNCERTAIN,
                    error=(f"digest mismatch after crash: expected {expected_post_digest}, got {actual_digest}"),
                )
            else:
                # Expected removal but file exists — effect uncertain
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.EFFECT_UNCERTAIN,
                    error=f"file exists but expected removal after crash: {file_path}",
                )

        # No pre-effect checkpoint — standard reconciliation
        full_path = Path(os.path.realpath(str(self._workspace / file_path)))
        if not full_path.exists():
            if expected_post_digest is None:
                return BuildActionExecution(
                    action_id=action_id,
                    status=BuildActionStatus.COMPLETED,
                )
            return BuildActionExecution(
                action_id=action_id,
                status=BuildActionStatus.FAILED,
                error=f"file missing during reconciliation: {file_path}",
            )

        actual_digest = hashlib.sha256(full_path.read_bytes()).hexdigest()
        if expected_post_digest is None:
            return BuildActionExecution(
                action_id=action_id,
                status=BuildActionStatus.FAILED,
                error=f"file exists but expected removal: {file_path}",
            )
        if actual_digest == expected_post_digest:
            return BuildActionExecution(
                action_id=action_id,
                status=BuildActionStatus.COMPLETED,
                post_image_digest=actual_digest,
            )
        return BuildActionExecution(
            action_id=action_id,
            status=BuildActionStatus.FAILED,
            error=(f"digest mismatch during reconciliation: expected {expected_post_digest}, got {actual_digest}"),
        )

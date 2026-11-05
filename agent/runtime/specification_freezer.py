"""Specification freezer — exact bytes, write-once immutable freeze."""

from __future__ import annotations

from pydantic import BaseModel

from agent.contracts.common import ArtifactRef
from agent.contracts.host import FreezeReceipt, ReceiptRef
from agent.contracts.scanner import ScannerEvidence
from agent.runtime.artifact_store import ArtifactStore
from agent.runtime.canonical_serialization import canonical_bytes, digest_raw
from agent.runtime.host_gap_analyzer import verify_structural_pass
from agent.runtime.receipt_store import ReceiptStore
from agent.runtime.scanner_check_registry import ScannerCheckRegistry
from agent.runtime.scanner_evidence import verify_scanner_evidence


class FreezeError(Exception):
    pass


class SpecificationFreezer:
    """Host-owned specification freezer.

    - Validates that the candidate has full scanner coverage.
    - Freezes exact bytes write-once.
    - Issues a FreezeReceipt outside the specification digest.
    """

    def __init__(
        self,
        artifact_store: ArtifactStore,
        receipt_store: ReceiptStore,
    ) -> None:
        self._store = artifact_store
        self._receipts = receipt_store

    def freeze(
        self,
        candidate_model: BaseModel,
        artifact_id: str,
        revision: int,
        contract_id: str,
        contract_version: str,
        scanner_evidence: ScannerEvidence,
        scanner_check_registry_ref: ArtifactRef,
        gap_result_ref: ArtifactRef,
        gap_receipt_ref: ReceiptRef,
        task_id: str,
        run_id: str,
        repository_identity_ref: str,
        authorization_receipt_id: str,
        authorization_receipt_digest: str,
        issuer_id: str = "host",
    ) -> FreezeReceipt:
        """Freeze only after exact structural, Scanner, and approval receipts verify."""
        digest_before_write = digest_raw(canonical_bytes(candidate_model))
        candidate_ref = ArtifactRef(
            artifact_id=artifact_id,
            artifact_revision=revision,
            artifact_digest=digest_before_write,
            contract_id=contract_id,
            contract_version=contract_version,
            serializer_profile="rfc8785-jcs-sha256-v1",
        )
        try:
            verify_structural_pass(
                self._store,
                self._receipts,
                task_id,
                run_id,
                gap_result_ref,
                gap_receipt_ref,
                candidate_ref,
            )
            registry = ScannerCheckRegistry(self._store, scanner_check_registry_ref)
            verify_scanner_evidence(
                self._store,
                self._receipts,
                scanner_evidence,
                candidate_ref,
                registry,
                task_id,
                run_id,
                repository_identity_ref,
            )
        except Exception as exc:
            raise FreezeError(f"Planning gates are not valid: {exc}") from exc
        if issuer_id != "host" or not self._receipts.verify(
            authorization_receipt_id,
            authorization_receipt_digest,
            f"approve-freeze:{digest_before_write}",
        ):
            raise FreezeError("host approval receipt is not verified")

        digest = self._store.put_immutable(candidate_model, artifact_id, revision, contract_id, contract_version)

        # Build artifact refs
        if digest != digest_before_write:
            raise FreezeError("candidate changed during freeze")
        # Store frozen copy
        frozen_digest = self._store.put_immutable(
            candidate_model, f"frozen-{artifact_id}", revision, contract_id, contract_version
        )
        frozen_ref = ArtifactRef(
            artifact_id=f"frozen-{artifact_id}",
            artifact_revision=revision,
            artifact_digest=frozen_digest,
            contract_id=contract_id,
            contract_version=contract_version,
            serializer_profile="rfc8785-jcs-sha256-v1",
        )

        freeze_receipt_id = f"freeze-{artifact_id}-rev{revision}"
        self._receipts.issue_verified(freeze_receipt_id, issuer_id, digest)

        return FreezeReceipt(
            candidate_ref=candidate_ref,
            frozen_ref=frozen_ref,
            scanner_receipt_ref=ReceiptRef(
                receipt_id=scanner_evidence.receipt_ref.receipt_id,
                receipt_digest=scanner_evidence.receipt_ref.receipt_digest,
                issuer_id="host",
            ),
            repository_identity_ref=repository_identity_ref,
            authorization_receipt_ref=ReceiptRef(
                receipt_id=authorization_receipt_id,
                receipt_digest=authorization_receipt_digest,
                issuer_id=issuer_id,
            ),
        )

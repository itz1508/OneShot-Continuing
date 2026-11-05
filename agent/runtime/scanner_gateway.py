"""Scanner gateway — single registered Scanner owner behind interface."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from agent.contracts.common import ArtifactRef
from agent.contracts.scanner import (
    ScannerFinding,
    ScannerOutcome,
    ScannerResult,
)

if TYPE_CHECKING:
    from agent.runtime.artifact_store import ArtifactStore


# Type alias: a detector takes artifact bytes and returns findings (empty = pass)
DetectorFn = Callable[[bytes], tuple[ScannerFinding, ...]]


class ScannerGatewayError(Exception):
    pass


class ScannerGateway:
    """Single registered Scanner owner.

    Only the host may dispatch scans. Denies unsupported categories
    and identity mismatches. Verifies content integrity against the
    artifact store, then invokes actual registered detectors.
    """

    def __init__(self, artifact_store: ArtifactStore | None = None) -> None:
        self._registered_capabilities: set[str] = set()
        self._detectors: dict[str, DetectorFn] = {}
        self._artifact_store = artifact_store

    def register_capability(self, capability_id: str) -> None:
        """Register a capability without a detector (capability will BLOCK at scan time)."""
        self._registered_capabilities.add(capability_id)

    def register_detector(self, capability_id: str, detector: DetectorFn) -> None:
        """Register a capability with an actual detector callable.

        The detector receives artifact bytes and returns a tuple of
        ScannerFinding objects. An empty tuple means the detector found
        no issues (PASS). A non-empty tuple means issues were found.
        """
        previous = self._detectors.get(capability_id)
        if previous is not None and previous is not detector:
            raise ScannerGatewayError("Scanner detector registration is immutable")
        self._registered_capabilities.add(capability_id)
        self._detectors[capability_id] = detector

    def scan_exact(
        self,
        candidate_ref: ArtifactRef,
        repository_identity: str,
        capabilities: tuple[str, ...],
        registry_ref: ArtifactRef | None = None,
    ) -> ScannerResult:
        """Scan exact candidate bytes for requested capabilities.

        Verifies content integrity by checking the artifact's stored digest
        matches the expected digest in the candidate_ref. Returns BLOCKED
        if the artifact store is unavailable or the artifact cannot be verified.
        """
        if not capabilities:
            return ScannerResult(
                request_id=f"scan-{candidate_ref.artifact_id}-{candidate_ref.artifact_revision}",
                outcome=ScannerOutcome.BLOCKED,
                limitation_reasons=("no Scanner capabilities requested",),
                candidate_ref=candidate_ref,
                repository_identity=repository_identity,
                registry_ref=registry_ref,
            )
        result = self._scan_exact_unbound(candidate_ref, repository_identity, capabilities)
        return result.model_copy(
            update={
                "candidate_ref": candidate_ref,
                "repository_identity": repository_identity,
                "requested_capabilities": capabilities,
                "registry_ref": registry_ref,
            }
        )

    def _scan_exact_unbound(
        self, candidate_ref: ArtifactRef, repository_identity: str, capabilities: tuple[str, ...]
    ) -> ScannerResult:
        unsupported = [c for c in capabilities if c not in self._registered_capabilities]
        if unsupported:
            return ScannerResult(
                request_id=f"scan-{candidate_ref.artifact_id}",
                outcome=ScannerOutcome.BLOCKED,
                capabilities_checked=(),
                capabilities_not_checked=capabilities,
                limitation_reasons=tuple(f"unsupported capability: {c}" for c in unsupported),
            )

        # Verify content integrity if artifact store is available
        if self._artifact_store is not None:
            stored_digest = self._artifact_store.get_digest(
                candidate_ref.artifact_id,
                candidate_ref.artifact_revision,
            )
            if stored_digest is None:
                return ScannerResult(
                    request_id=f"scan-{candidate_ref.artifact_id}-{candidate_ref.artifact_revision}",
                    outcome=ScannerOutcome.BLOCKED,
                    capabilities_checked=(),
                    capabilities_not_checked=capabilities,
                    limitation_reasons=("artifact not found in store",),
                )
            if stored_digest != candidate_ref.artifact_digest:
                return ScannerResult(
                    request_id=f"scan-{candidate_ref.artifact_id}-{candidate_ref.artifact_revision}",
                    outcome=ScannerOutcome.BLOCKED,
                    capabilities_checked=(),
                    capabilities_not_checked=capabilities,
                    limitation_reasons=("content digest mismatch",),
                    findings=(
                        ScannerFinding(
                            finding_id=f"finding-{candidate_ref.artifact_id}",
                            capability=capabilities[0] if capabilities else "unknown",
                            severity="error",
                            message=f"expected {candidate_ref.artifact_digest}, got {stored_digest}",
                        ),
                    ),
                )
        else:
            # No artifact store — cannot verify content integrity
            return ScannerResult(
                request_id=f"scan-{candidate_ref.artifact_id}-{candidate_ref.artifact_revision}",
                outcome=ScannerOutcome.BLOCKED,
                capabilities_checked=(),
                capabilities_not_checked=capabilities,
                limitation_reasons=("no artifact store configured for content verification",),
            )

        # Content verified — now invoke actual registered detectors
        all_findings: list[ScannerFinding] = []
        checked: list[str] = []
        not_checked: list[str] = []
        reasons: list[str] = []

        for cap in capabilities:
            detector = self._detectors.get(cap)
            if detector is None:
                # Capability is registered but has no detector — cannot verify
                not_checked.append(cap)
                reasons.append(f"no detector registered for capability: {cap}")
                continue

            # Retrieve artifact content for detector execution
            try:
                artifact_bytes = self._artifact_store.get_verified(
                    candidate_ref.artifact_id,
                    candidate_ref.artifact_revision,
                )
                findings = detector(artifact_bytes)
            except Exception as exc:
                not_checked.append(cap)
                reasons.append(f"detector error for {cap}: {exc}")
                continue

            checked.append(cap)
            all_findings.extend(findings)

        if not_checked:
            return ScannerResult(
                request_id=f"scan-{candidate_ref.artifact_id}-{candidate_ref.artifact_revision}",
                outcome=ScannerOutcome.BLOCKED,
                capabilities_checked=tuple(checked),
                capabilities_not_checked=tuple(not_checked),
                limitation_reasons=tuple(reasons),
                findings=tuple(all_findings),
            )

        # All detectors executed — PASS only if no findings
        return ScannerResult(
            request_id=f"scan-{candidate_ref.artifact_id}-{candidate_ref.artifact_revision}",
            outcome=ScannerOutcome.PASS if not all_findings else ScannerOutcome.FAIL,
            capabilities_checked=capabilities,
            capabilities_not_checked=(),
            findings=tuple(all_findings),
        )

    @property
    def supported_capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._registered_capabilities))

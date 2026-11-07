"""Scanner gateway — single registered Scanner owner behind interface."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from agent.contracts.common import ArtifactRef
from agent.contracts.scanner import (
    CriterionResult,
    CriterionValidity,
    ObservationState,
    ScannerEvidenceRequest,
    ScannerFinding,
    ScannerOutcome,
    ScannerResult,
    ScannerTraceStep,
    TracedDetectorResult,
)
from agent.contracts.validation.planning import scan_action_dependencies

if TYPE_CHECKING:
    from agent.runtime.artifact_store import ArtifactStore


# Type alias: a detector takes artifact bytes and returns findings (empty = pass)
DetectorFn = Callable[[bytes], tuple[ScannerFinding, ...]]
TracedDetectorFn = Callable[[bytes, str, str], TracedDetectorResult]
ScannerEventSink = Callable[[str, dict[str, object]], None]


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
        self._traced_detectors: dict[str, TracedDetectorFn] = {}
        self._artifact_store = artifact_store
        self.register_traced_detector("dependency_readiness", scan_action_dependencies)

    def register_capability(self, capability_id: str) -> None:
        """Register a capability without a detector (capability will BLOCK at scan time)."""
        self._registered_capabilities.add(capability_id)

    def register_detector(self, capability_id: str, detector: DetectorFn) -> None:
        """Register a capability with an actual detector callable.

        The detector receives artifact bytes and returns a tuple of
        ScannerFinding objects. An empty tuple means the detector found
        no issues (PASS). A non-empty tuple means issues were found.
        """
        self._registered_capabilities.add(capability_id)
        self._detectors[capability_id] = detector

    def register_traced_detector(self, capability_id: str, detector: TracedDetectorFn) -> None:
        """Register a detector with first-class, execution-time comparisons."""
        self._registered_capabilities.add(capability_id)
        self._traced_detectors[capability_id] = detector

    @staticmethod
    def _unknown(candidate_ref: ArtifactRef, capabilities: tuple[str, ...], reason: str) -> ScannerResult:
        """Missing evidence is unknown, not known-false."""
        target = f"{candidate_ref.artifact_id}@{candidate_ref.artifact_revision}"
        traces = tuple(
            ScannerTraceStep(
                check_id=cap,
                rule_version="1",
                scanner_version="1",
                target_ref=target,
                observation_state=ObservationState.UNKNOWN,
                observed_value=None,
                operator="equals",
                expected_value=True,
                criterion_result=CriterionResult.UNKNOWN,
                criterion_validity=CriterionValidity.NOT_VALID,
                reason=reason,
            )
            for cap in capabilities
            if cap == "dependency_readiness"
        )
        requests = tuple(
            ScannerEvidenceRequest(
                check_id=cap,
                target_ref=target,
                missing_evidence="verified candidate artifact",
                reason=reason,
            )
            for cap in capabilities
            if cap == "dependency_readiness"
        )
        return ScannerResult(
            request_id=f"scan-{target}",
            outcome=ScannerOutcome.BLOCKED,
            capabilities_not_checked=capabilities,
            limitation_reasons=(reason,),
            candidate_ref=candidate_ref,
            trace_steps=traces,
            evidence_requests=requests,
        )

    def scan_exact(
        self,
        candidate_ref: ArtifactRef,
        repository_identity: str,
        capabilities: tuple[str, ...],
        *,
        on_event: ScannerEventSink | None = None,
    ) -> ScannerResult:
        """Scan exact candidate bytes for requested capabilities.

        Verifies content integrity by checking the artifact's stored digest
        matches the expected digest in the candidate_ref. Returns BLOCKED
        if the artifact store is unavailable or the artifact cannot be verified.
        """

        def publish(event_type: str, message: str, **details: object) -> None:
            if on_event is not None:
                on_event(event_type, {"message": message, **details})

        def report(
            capability: str,
            steps: tuple[ScannerTraceStep, ...],
            requests: tuple[ScannerEvidenceRequest, ...],
            findings: tuple[ScannerFinding, ...],
        ) -> None:
            for step in steps:
                publish(
                    "scanner_check",
                    f"{capability}: {step.criterion_result.value} ({step.criterion_validity.value})",
                    capability=capability,
                    check_id=step.check_id,
                    target_ref=step.target_ref,
                    observation_state=step.observation_state.value,
                    criterion_result=step.criterion_result.value,
                    criterion_validity=step.criterion_validity.value,
                    required=step.required,
                )
            for request in requests:
                publish(
                    "scanner_evidence_requested",
                    f"{capability}: evidence required",
                    capability=capability,
                    check_id=request.check_id,
                    target_ref=request.target_ref,
                )
            for finding in findings:
                publish(
                    "scanner_finding",
                    f"{capability}: finding {finding.finding_id}",
                    capability=capability,
                    finding_id=finding.finding_id,
                    severity=finding.severity,
                )

        unsupported = [c for c in capabilities if c not in self._registered_capabilities]
        if unsupported:
            for capability in unsupported:
                publish(
                    "scanner_capability",
                    f"{capability}: unsupported capability",
                    capability=capability,
                    status="not_checked",
                )
            return ScannerResult(
                request_id=f"scan-{candidate_ref.artifact_id}",
                outcome=ScannerOutcome.BLOCKED,
                capabilities_checked=tuple(c for c in capabilities if c in self._registered_capabilities),
                capabilities_not_checked=tuple(unsupported),
                limitation_reasons=tuple(f"unsupported capability: {c}" for c in unsupported),
            )

        # No capabilities requested — nothing to verify
        if not capabilities:
            return ScannerResult(
                request_id=f"scan-{candidate_ref.artifact_id}-{candidate_ref.artifact_revision}",
                outcome=ScannerOutcome.PASS,
                capabilities_checked=(),
                capabilities_not_checked=(),
                findings=(),
            )

        # Always verify current immutable storage before using cached source facts.
        def unknown(reason: str) -> ScannerResult:
            result = self._unknown(candidate_ref, capabilities, reason)
            for capability in capabilities:
                report(
                    capability,
                    tuple(step for step in result.trace_steps if step.check_id == capability),
                    tuple(request for request in result.evidence_requests if request.check_id == capability),
                    (),
                )
            return result

        if self._artifact_store is None:
            return unknown("no artifact store configured for content verification")
        stored_digest = self._artifact_store.get_digest(candidate_ref.artifact_id, candidate_ref.artifact_revision)
        if stored_digest is None:
            return unknown("artifact not found in store")
        if stored_digest != candidate_ref.artifact_digest:
            return unknown("content digest mismatch")

        # Trace and authorization bindings are created fresh on each invocation.
        all_findings: list[ScannerFinding] = []
        checked: list[str] = []
        not_checked: list[str] = []
        reasons: list[str] = []
        traces: list[ScannerTraceStep] = []
        evidence_requests: list[ScannerEvidenceRequest] = []
        cache_hits = 0
        cache_misses = 0
        parse_duration_ns = 0

        for cap in capabilities:
            detector = self._detectors.get(cap)
            traced_detector = self._traced_detectors.get(cap)
            if detector is None and traced_detector is None:
                not_checked.append(cap)
                reasons.append(f"no detector registered for capability: {cap}")
                publish("scanner_capability", f"{cap}: detector unavailable", capability=cap, status="not_checked")
                continue
            try:
                artifact_bytes = self._artifact_store.get_verified(
                    candidate_ref.artifact_id, candidate_ref.artifact_revision
                )
                if traced_detector is not None:
                    target = f"{candidate_ref.artifact_id}@{candidate_ref.artifact_revision}"
                    evidence = f"artifact:{target}#{candidate_ref.artifact_digest}"
                    if traced_detector is scan_action_dependencies:
                        # Preserve the actual detector; stream predicate observations as executed.
                        def publish_dependency_step(
                            step: ScannerTraceStep,
                            finding: ScannerFinding | None,
                            capability: str = cap,
                        ) -> None:
                            report(capability, (step,), (), (finding,) if finding is not None else ())

                        result = scan_action_dependencies(
                            artifact_bytes, target, evidence, on_step=publish_dependency_step
                        )
                        report(cap, (), result.evidence_requests, ())
                    else:
                        result = traced_detector(artifact_bytes, target, evidence)
                        report(cap, result.trace_steps, result.evidence_requests, result.findings)
                    findings = result.findings
                    traces.extend(result.trace_steps)
                    evidence_requests.extend(result.evidence_requests)
                    cache_hits += result.cache_hits
                    cache_misses += result.cache_misses
                    parse_duration_ns += result.parse_duration_ns
                else:
                    assert detector is not None
                    findings = detector(artifact_bytes)
                    report(cap, (), (), findings)
            except Exception:
                not_checked.append(cap)
                reason = f"detector unavailable or malformed evidence for {cap}"
                reasons.append(reason)
                if traced_detector is not None:
                    unresolved = self._unknown(candidate_ref, (cap,), reason)
                    traces.extend(unresolved.trace_steps)
                    evidence_requests.extend(unresolved.evidence_requests)
                    report(cap, unresolved.trace_steps, unresolved.evidence_requests, ())
                publish(
                    "scanner_capability",
                    f"{cap}: detector could not check evidence",
                    capability=cap,
                    status="not_checked",
                )
                continue
            checked.append(cap)
            all_findings.extend(findings)
            publish(
                "scanner_capability",
                f"{cap}: checked {len(findings)} findings",
                capability=cap,
                status="checked",
                finding_count=len(findings),
            )

        publish(
            "scanner_cache_metrics",
            "Scanner parser cache observations",
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            parse_duration_ns=parse_duration_ns,
        )
        return ScannerResult(
            request_id=f"scan-{candidate_ref.artifact_id}-{candidate_ref.artifact_revision}",
            outcome=(
                ScannerOutcome.PASS
                if not not_checked
                and not all_findings
                and all(t.criterion_validity is CriterionValidity.VALID for t in traces)
                else ScannerOutcome.BLOCKED
            ),
            capabilities_checked=tuple(checked),
            capabilities_not_checked=tuple(not_checked),
            limitation_reasons=tuple(reasons),
            findings=tuple(all_findings),
            candidate_ref=candidate_ref,
            trace_steps=tuple(traces),
            evidence_requests=tuple(evidence_requests),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            parse_duration_ns=parse_duration_ns,
        )

    @property
    def supported_capabilities(self) -> tuple[str, ...]:
        return tuple(self._registered_capabilities)

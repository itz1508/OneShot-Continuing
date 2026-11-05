"""Canonical Gap Analysis ownership and missing-capability detection."""

from __future__ import annotations

from agent.contracts.common import DiagnosticStatus
from agent.gap_analysis import (
    CapabilityConsumer,
    CapabilityProducer,
    CapabilityRequirement,
    MissingCapabilityAnalyzer,
    RepositorySnapshot,
    audit_repository,
)


def test_missing_capability_reports_producer_symbol_and_consumer_gaps() -> None:
    requirements = (
        CapabilityRequirement(
            capability_id="tool_registry",
            producers=(CapabilityProducer(path="owner.py", symbols=("ToolRegistry",)),),
            consumers=(CapabilityConsumer(path="consumer.py", reference="ToolRegistry"),),
        ),
    )
    snapshot = RepositorySnapshot(
        source_id="fixture:broken",
        files={"owner.py": "class WrongOwner: pass\n", "consumer.py": "value = None\n"},
    )

    result = MissingCapabilityAnalyzer().analyze(snapshot, requirements)

    assert result.diagnostic_status is DiagnosticStatus.NOT_VALID
    assert {(gap.kind, gap.path) for gap in result.gaps} == {
        ("missing_symbol", "owner.py"),
        ("unresolved_consumer", "consumer.py"),
    }


def test_current_repository_closes_the_accepted_capability_set() -> None:
    result = audit_repository(".")
    assert result.gaps == ()
    assert result.diagnostic_status is DiagnosticStatus.VALID


def test_missing_producer_file_still_detected_from_synthetic_snapshot() -> None:
    requirements = (
        CapabilityRequirement(
            capability_id="scanner_check_registry",
            producers=(
                CapabilityProducer(path="agent/runtime/scanner_check_registry.py", symbols=("ScannerCheckRegistry",)),
            ),
        ),
    )
    result = MissingCapabilityAnalyzer().analyze(
        RepositorySnapshot(source_id="fixture:missing", files={}), requirements
    )
    assert [(gap.kind, gap.path) for gap in result.gaps] == [
        ("missing_producer", "agent/runtime/scanner_check_registry.py")
    ]

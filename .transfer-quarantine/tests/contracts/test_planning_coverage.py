"""Planning owns the eight issue categories across distinct check owners."""

from agent.contracts.planning_coverage import ISSUE_CATEGORIES, planning_coverage
from agent.contracts.scanner import ScannerResult
from agent.contracts.validation.structural import CONCERNS
from agent.runtime.controller import HostController
from agent.runtime.scanner_evidence import persist_scan_result
from tests.fixtures.scanner import passing_scan
from tests.fixtures.structural_gap import passing_gap


def test_scanner_check_alone_reports_uncovered_planning_categories():
    coverage = planning_coverage(structural_concerns=frozenset(), scanner_capabilities=("syntax",))
    assert coverage.category_sources["buildability"] == ("scanner:syntax",)
    assert "concurrency" in coverage.uncovered_categories
    assert "security" in coverage.uncovered_categories


def test_structural_and_scanner_checks_share_one_issue_taxonomy():
    coverage = planning_coverage(structural_concerns=CONCERNS, scanner_capabilities=("syntax", "types"))
    assert set(coverage.category_sources) == set(ISSUE_CATEGORIES)
    assert coverage.uncovered_categories == ()
    assert coverage.category_sources["buildability"] == ("scanner:syntax",)
    assert coverage.category_sources["interface"] == ("scanner:types",)
    assert coverage.category_sources["concurrency"] == ("structural:concurrency",)


def test_unknown_scanner_check_is_recorded_without_claiming_category():
    coverage = planning_coverage(structural_concerns=frozenset(), scanner_capabilities=("custom",))
    assert coverage.unmapped_scanner_capabilities == ("custom",)
    assert coverage.uncovered_categories == ISSUE_CATEGORIES


def test_host_persists_category_coverage_with_exact_scan(tmp_path):
    controller = HostController(tmp_path)
    gap = passing_gap(controller)
    evidence = passing_scan(controller, gap)
    raw = controller.artifact_store.get_verified(evidence.result_ref.artifact_id, 1)
    result = ScannerResult.model_validate_json(raw)
    assert result.planning_coverage is not None
    assert result.planning_coverage.uncovered_categories == ()
    assert result.planning_coverage.category_sources["buildability"] == ("scanner:syntax",)

    assert controller.scanner_checks is not None
    forged = result.model_copy(
        update={
            "planning_coverage": planning_coverage(
                structural_concerns=frozenset(), scanner_capabilities=("syntax", "types")
            )
        }
    )
    rejected = persist_scan_result(
        controller.artifact_store, controller.receipt_store, forged, controller.scanner_checks
    )
    assert rejected.evidence is None

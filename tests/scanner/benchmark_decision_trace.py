"""Reproducible scanner cache benchmark using legacy validator oracles.

This is a focused benchmark for the new vertical slice, not an existing
multi-category scanner suite. Prints measured nanoseconds from CI runner.
"""

from __future__ import annotations

import json
from time import perf_counter_ns

from agent.contracts.validation.planning import (
    parse_action_dependency_facts,
    scan_action_dependencies,
    validate_action_graph,
)
from agent.runtime.canonical_serialization import canonical_bytes
from test_decision_trace import make_planning_record, revised_record


def timed_scan(source: bytes, target: str):
    started = perf_counter_ns()
    result = scan_action_dependencies(source, target, f"artifact:{target}#verified")
    return result, perf_counter_ns() - started


def main() -> None:
    # The legacy validator's output remains the oracle; no relabeling.
    original = make_planning_record()
    repaired = revised_record(original)
    legacy_bad = validate_action_graph(original.candidate.build_spec)
    legacy_good = validate_action_graph(repaired.candidate.build_spec)
    assert legacy_bad == ["action consumer depends on unknown action absent"]
    assert legacy_good == []

    original_bytes = canonical_bytes(original)
    repaired_bytes = canonical_bytes(repaired)
    parse_action_dependency_facts.cache_clear()

    cold, cold_total = timed_scan(original_bytes, "draft@1")
    warm, warm_total = timed_scan(original_bytes, "draft@1")
    changed, changed_total = timed_scan(repaired_bytes, "draft@2")

    assert cold.cache_misses == 1 and cold.cache_hits == 0
    assert warm.cache_hits == 1 and warm.cache_misses == 0
    assert changed.cache_misses == 1
    assert cold.findings == warm.findings
    assert cold.trace_steps == warm.trace_steps
    assert bool(cold.findings) == bool(legacy_bad)
    assert bool(changed.findings) == bool(legacy_good)
    assert cold.trace_steps[-1].observed_value is False
    assert changed.trace_steps[-1].observed_value is True

    previous_misses = parse_action_dependency_facts.cache_info().misses
    parse_action_dependency_facts("parser-v2", original_bytes)
    assert parse_action_dependency_facts.cache_info().misses == previous_misses + 1
    info = parse_action_dependency_facts.cache_info()
    assert info.currsize <= 128 and info.maxsize == 128

    print(json.dumps({
        "oracle_original": legacy_bad,
        "oracle_repaired": legacy_good,
        "new_original_findings": [item.message for item in cold.findings],
        "new_repaired_findings": [item.message for item in changed.findings],
        "oracle_equivalence": True,
        "cold_total_ns": cold_total,
        "warm_total_ns": warm_total,
        "changed_total_ns": changed_total,
        "cold_parse_ns": cold.parse_duration_ns,
        "warm_parse_ns": warm.parse_duration_ns,
        "changed_parse_ns": changed.parse_duration_ns,
        "cold_hits": cold.cache_hits,
        "cold_misses": cold.cache_misses,
        "warm_hits": warm.cache_hits,
        "warm_misses": warm.cache_misses,
        "changed_misses": changed.cache_misses,
        "parser_version_invalidation": True,
        "cache_maxsize": info.maxsize,
        "cache_currsize": info.currsize,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

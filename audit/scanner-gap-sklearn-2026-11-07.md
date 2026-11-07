# Scanner gap audit — scikit-learn fixture evaluation (2026-11-07)

**Lesson:** independently labeled good/bad/unknown graph fixtures exposed readiness false-positives that a single missing-dependency oracle could not detect; deterministic fixes were rescored without changing the labels.

## Scope and evaluator

Repository: `itz1508/OneShot-Continuing`, existing draft [PR #5](https://github.com/itz1508/OneShot-Continuing/pull/5).
Measured unit: the *real* `ScannerGateway.scan_exact` on exact, immutable
`ArtifactStore` bytes. The oracle is a manually labeled matched-case corpus in
`tests/scanner/evaluate_gap_sklearn.py` (20 cases: 5 clear, 9 defective,
6 unknown/unverified). A separate fixed case checks unsupported capability
behavior. `scikit-learn==1.8.0` provides `confusion_matrix` and
`classification_report` only; it is **not** imported by the host or used for
authorization, scanner verdicts, confidence scores, or model training.

Reproduce (Python 3.11/3.12, dependencies synced):

    uv run --no-sync --with scikit-learn==1.8.0 python tests/scanner/evaluate_gap_sklearn.py

## Before and after (real GitHub Actions jobs)

| Measurement | Pre-fix `054d1d4b` | Corrected `58236a98` |
| --- | ---: | ---: |
| Scikit-learn accuracy on labeled fixtures | 14 / 20 (70%) | 20 / 20 (100%) |
| Defect recall | 4 / 9 (44.4%) | 9 / 9 (100%) |
| Unknown classifications correct | 5 / 6 | 6 / 6 |
| Missing/extra classification labels | 6 mismatches | 0 mismatches |
| Confusion matrix (rows true, columns predicted; clear/defect/unknown) | `[[5,0,0],[5,4,0],[1,0,5]]` | `[[5,0,0],[0,9,0],[0,0,6]]` |

Evidence: [baseline CI (expected evaluation failure)](https://github.com/itz1508/OneShot-Continuing/actions/runs/42367496042);
[corrected CI (green, Python 3.11 and 3.12)](https://github.com/itz1508/OneShot-Continuing/actions/runs/42367923707).
These numbers describe **this fixed synthetic corpus**, not operational false-positive
rates, generalization, or probability of Build success.

## Verified gaps and changes

1. **Missing cycle detection:** self, two-node, and three-node cycles were
   incorrectly treated as clear. The existing dependency detector now uses a
   deterministic non-recursive graph traversal and emits an executed
   `dependency_acyclic` comparison and a finding on cycles.
2. **Missing duplicate-ID detection:** two duplicate-action fixtures were
   incorrectly treated as clear. The existing detector now compares each
   action ID occurrence count to one (`dependency_unique_ids`) and emits a
   typed finding when unequal.
3. **False empty-scan readiness:** an empty capability tuple returned
   `ScannerOutcome.PASS`. It now returns `NOT_RUN`, and the typed API/CLI
   request rejects empty and duplicate capability lists.
4. **Unsupported check misreported:** a mix of supported and unsupported
   capabilities previously reported the supported ones as checked without
   executing them. All requested checks are now `not_checked` if admission
   stops before execution.
5. **Incomplete live event details:** stream check records lacked the
   comparison's observed/expected values, operator, check versions and
   evidence references. They now include these safe typed fields; string
   observations are withheld from streamed details to avoid exporting
   private source text, while the full trace remains in immutable
   `ScannerResult` artifacts.
6. **Event-delivery coupling:** optional CLI observers could interrupt the
   authoritative scan; EventStore write failures could be misclassified
   as detector unknown. Listener exceptions no longer alter decisions,
   while event persistence failure terminates the scan without
   publishing a false completion record.
7. **Unbounded event replay:** SSE queries scanned the entire task history
   before Python-side cursor filtering. SQLite now supports indexed
   `after`/`limit` cursors and the MVP reads 256-event pages, retaining the
   existing SSE protocol and EventStore.
8. **Real receipt positive path missing:** added an HTTP integration test
   that executes the existing HostGapAnalyzer over synthetic source/registry
   fixtures, obtains its actual host-issued receipt, and successfully
   dispatches the Scanner without bypassing receipt validation.

All source changes stay within existing contracts, detector,
Controller, ArtifactStore, EventStore, MVP adapter and regression tests.
The dependency parser version remains unchanged because its pure facts are
unchanged; the rule and scanner versions are incremented to `2`.

## Evidence boundaries

- All 20 labels are synthetic and fixed. No model was fit, and no training
  performance or calibrated build-success probability is claimed.
- Full independent Planning → Build → Sandbox → E2E with production source
  identity remains unverified. This is a scanner acceptance suite only.
- Other technical Scanner detectors, eight Planning issue categories, and
  cross-repository evidence validation are not established by this limited
  dependency-graph evaluation. Unsupported or unknown checks remain blocking.
- The positive structural-gap receipt test uses a genuine host receipt but
  synthetic upstream inputs and a manually advanced Planning checkpoint.
  It does not prove a complete Discovery/Research/Planning execution.

Original legacy `validate_action_graph` messages and tests are retained;
`tests/scanner/benchmark_decision_trace.py` continues to check legacy oracle
equivalence for the existing missing-dependency case.

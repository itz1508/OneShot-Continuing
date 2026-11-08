# Planning → Scanner → Repair → Build: evidence-bound integration audit

**Snapshot:** `itz1508/OneShot-Continuing` at `394ada960f99000395c7cd8de50ae21ab8c3af20`.

## What the new test actually executes

A single real `HostController` owns `ArtifactStore`, `ReceiptStore`, `EventStore`, `HostGapAnalyzer`, `ScannerGateway`, and authorized Planning CAS. A synthetic PlanningRecord with a missing dependency is scanned, repaired, re-evaluated through the real structural analyzer, and re-scanned. The final revised bytes are used by the existing PackageLock, BuildAdmission, EffectExecutor, two wave-preimage checks, and independent filesystem readback recorded in BuildValidationRecord.

**Synthetic only:** Research/Audit payloads and walking-skeleton observations come from `tests/fixtures/structural_gap.py`. Their source labels do not represent a production inspection or a deployed sandbox execution. The readback test verifies physical file bytes, not real application behavior.

## P0 admission gaps — remain unresolved

1. `SpecificationFreezer.freeze` accepts caller-provided Scanner and authorization receipt IDs/digests without validating their subjects. The frozen artifact copy is created before any gate.
2. `PackageLock.lock` checks upstream artifact digests but not a trusted FreezeReceipt, exact accepted plan revision, valid Scanner pass, or Fixture/Chaos readiness.
3. `BuildAdmission.admit` can accept a pinned BuildSpecification and PackageLock without receiving a ScannerEvidence result/receipt or checking the exact structural-gap candidate. The integration test exercises this legacy path, **not** an admitted production-ready build.
4. Only `dependency_readiness` has a real evidence-traced Scanner detector. Independent acceptance of other capabilities, external tool identities, and Modal Sandbox execution remain unproven.
5. `BuildValidationRecord` is constructed after an actual readback, but no host-owned independent verification receipt/promote-to-completion dispatch is demonstrated.

**Disposition: NOT READY for full Planning-to-Build E2E.** The fixture demonstrates actual Runtime components and narrows the remaining contract work. Do not claim a complete accepted/specification-locked production pipeline from its results.

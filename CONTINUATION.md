# OneShot-Continuing

## Repository status

This repository is a **detached continuation snapshot** of
[`itz1508/OneShot`](https://github.com/itz1508/OneShot). It is not a fork and
does not mirror upstream history.

- Snapshot created: 2026-11-04
- Upstream repository: `itz1508/OneShot`
- Upstream branch: `main`
- Exact upstream commit imported (no upstream history imported):
  `78162220d545f04206a940c38e33adc031d96f2d`
  ("docs: show named Meta, Baseten and Modal products in help and build lifecycle",
  committed 2026-11-04T19:06:16-08:00)
- Method: shallow fetch of upstream `main` to a pristine detached tree, then a
  **new, independent Git history** initialized in this directory. No upstream
  commits, branches, tags, or remotes were carried over.

Continued work now lives only in this repository. Nothing here is pushed back
to `itz1508/OneShot`; do not add that repository as a push remote.

## Provenance boundary (hackathon disclosure)

The OneShot codebase imported above **predates this continuation effort** and
was not created as part of it. Pre-existing baseline includes, without
limitation: the host-owned `agent/` kernel (contracts, runtime, authorization,
recovery), the FastAPI/React MVP under `mvp/` and `web/`, Research and
read-only Audit, MCP Research, the MCP + model connector settings, Modal
deployment surfaces, tests, CI, docs and screenshots.

**New work begins with this repository's own commits.** Only functionality
introduced by commits in this repository — and clearly identified as such in
the demo and submission notes — may be presented as newly built work. Baseline
functionality may be shown only when necessary to provide context and must be
disclosed as pre-existing, with the import commit above cited.

Before presenting, record in this section (and in the demo):

- [x] the exact list of features newly built in this continuation effort (audited delta below)
- [x] the commit range / release containing them (audited delta below)
- [x] which existing OneShot capabilities were used unchanged as context (audited delta below)

## Evidence boundary

- Every claim must identify the tested revision.
- The synthetic browser demo under `web/public/demo.html` (see `web/demo/`) is
  a visualization: it does not call a backend, MCP server, or model, and it is
  not evidence of production execution.
- Health endpoints are not proof of MCP connectivity or live model inference.

## Licence and rights

Only include code, data, media, and assets you have the right to use. Keep
credentials in environment variables; never commit secrets (only `.env.example`
placeholders).

## 2026-11-05T04:45:37-08:00 — Continuation delta and evidence boundary

- **Inherited, not newly built:** source from `itz1508/OneShot` `78162220d545f04206a940c38e33adc031d96f2d`, imported as detached root `100365f52faf`. This includes the host, stage contracts, FastAPI/React MVP, MCP Research, read-only Audit, standalone Modal Sandbox, CI and tests.
- **New continuation UI change:** `15303a9674b73570142785fbedaf2477806ca16a` introduced read-only configured model API metadata and connector assertions in `web/src/main.jsx` and `web/tests/connectors.spec.js`. No task-level model picker or working Call for Help hook was added.
- **New documentation and visual work:** `52dc3a16c6b7` added the video evidence guide; later README and workflow animation work culminated in `a2c29610448a753d4ceac3da20254eca63aee30a` (`docs/workflow.gif`, `docs/workflow.html`). These are illustrations, not executed workflow stages.
- **Observed CI:** [run 42027538233](https://github.com/itz1508/OneShot-Continuing/actions/runs/42027538233) succeeded at `a2c2961` for Python 3.11/3.12 checks. Earlier MVP and Research/Audit CI at `1280f06` succeeded. No complete connected Discovery-first Build-through-independent-E2E run was observed.
- **Remaining work:** refer to `audit/workflow-alignment-2026-11-05.md` for implementation gaps and public-to-internal naming.

## 2026-11-05T19:10:17-08:00 — Discovery PRE/POST automation in OneShot-Continuing

**One-line summary:** PRE creates a source-bound Research request; POST preserves Research evidence without authorizing Build.

- **Active target:** `itz1508/OneShot-Continuing`, branch `feat/discovery-sandwich-20261105`, draft [PR #3](https://github.com/itz1508/OneShot-Continuing/pull/3); based on independent Continuing main `13720b7495d2ef86897ad9f13046b563c0969c5f`. No work from this branch was pushed to or merged into the frozen OneShot repository.
- **Implementation:** `agent/contracts/discovery_sandwich.py`, `agent/runtime/discovery_sandwich.py`, existing Host/controller and MVP Research routing; immutable PRE/request/POST artifact references, synthetic Catalog guidance, bounded read-only source inventory, exact message/revision binding, and recovery reconciliation. Existing six role stages, Planning Scanner, and Build admission remain unchanged.
- **Frontend:** Opt-in Auto Research checkbox submits task, attaches SSE, dispatches Research, and restores the persisted result without an extra Run click. Manual Research remains supported.
- **Verified evidence:** Python 3.11/3.12 CI, MVP backend/frontend integration, Research/Audit, and Host integrity green at `f70ad28af506b60f4a3181470d39ef42e631d668` and `8e2853582142d59a741540d2308af32b097235a3`. The connected MCP stdio fixture test asserts PRE + Research + POST lineage; no live provider inference is claimed.
- **Browser E2E:** A Chromium Playwright job was added to `.github/workflows/mvp.yml`; its first run was pending browser dependency installation when this record was written. Do not treat it as verified until the workflow reports an observed outcome.
- **Outstanding:** Model-generated intent summary; authenticated external thread-message integration; durable memory/thread scanners; complete source identity; code-aware Audit mapping and canonical stage handoff; connected Planner/Scanner/Fixture/Chaos/Build/independent E2E. PR remains draft and unmerged.

## 2026-11-06T01:06:45-08:00 — Active architectural decision and stale-reference cleanup

**One-line summary:** OneShot-Continuing now documents one Runtime-controlled workflow without standalone Package Lock/Build Admission stages; legacy code remains until a safe tested migration.

- **Current decision:** [README.md](README.md#workflow-and-authority) supersedes earlier workflow diagrams, older README narratives, previous Library plans for frozen OneShot, and the speculative Python orchestrator proposal. One Runtime/Controller controls all stages, approval, Preflight, Sandbox, memory checkpoints, effects and recovery.
- **Retained roles:** read-only Audit PRE, Host Research request preparation, Researcher, read-only Audit POST, Planning (including Scanner), Fixture Baseline/Chaos scenario readiness, exact user approval, Builder candidate preparation, runtime Preflight/Sandbox, independent integration/E2E/chaos validation, completion and trusted memory.
- **Memory:** `memory_prelight` freezes approval-bound context before Build and `memory_validation` records independently verified outcomes. Ordinary artifacts, checkpoints and five journals remain distinct. No vector/second memory framework is specified.
- **Legacy distinction:** Existing `PackageLockReceipt` and `BuildAdmissionReceipt` implementation is not approved architecture, but its safety controls must remain until an evidence-backed migration; ordinary Python/npm dependency lockfiles stay intact.
- **Changes in this revision:** documentation and agent guidance only; workflow YAML, guards, Sandbox implementation and E2E code not yet migrated. PR #3 remains draft. No main-branch merge and no change to frozen `itz1508/OneShot`.

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

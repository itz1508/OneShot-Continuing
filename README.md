# OneShot-Continuing

**Active engineering repository:** [`itz1508/OneShot-Continuing`](https://github.com/itz1508/OneShot-Continuing). The imported `itz1508/OneShot` is **frozen provenance, not a modification target**.

> **Current architecture decision — 2026-11-06.** This section supersedes the earlier README workflow description, animated diagram, audit proposal, old Library plans, and proposed standalone orchestrator. It specifies the **target**, not a claim of completed implementation. [Implementation status](#implementation-status) distinguishes shipped behavior from work still needed.

## Workflow and authority

The **API** accepts requests; the **Runtime / Controller remains in control across every stage**, validates each return, and alone owns transitions, approval enforcement, agent routing, artifact/receipt storage, TaskTodo scheduling, persistence, recovery, and cleanup.

```text
API
 |
 v
Runtime / Controller — encloses all transitions and result handoffs
 |
 +-- Audit PRE (read-only local discovery, provisional requirements)
 +-- Research request preparation (Host-bound targeted questions)
 +-- Researcher (sourced external evidence and fixture guidance)
 +-- Audit POST (read-only applicability, conflicts, source mapping)
 +-- Planning (review, design/refactoring PLAN, gap resolution, Scanner)
 +-- Build Baseline / Fixture Validation (required files, dependencies,
 |     configuration, assets, expected checks, fault/recovery SCENARIOS)
 +-- User Approval (exact plan revision + source checkpoint + scope)
 +-- Memory Prelight (Host-created immutable approval-bound context)
 +-- Build
 |    Builder: candidate change preparation within approved TaskTodos
 |    Runtime Preflight: check permissions, paths, preimages, tools, state
 |    Runtime Sandbox: apply candidates and run registered checks
 +-- Independent Validation (integration, E2E, regression, acceptance,
 |     applicable executable chaos/recovery tests)
 +-- Completion (source promotion ONLY after independent evidence;
      reconciliation, cleanup, evidence retention, memory promotion)
```

Every agent reports back to the Runtime. Neither an agent, a To-Do, nor a model response grants authorization or advances the stage. Catalog examples guide PRE and Research; they are **not** evidence.

## Responsibilities and nonnegotiable boundaries

| Owner | Contract |
| --- | --- |
| Audit PRE | Read-only inspection of repository, filesystem, permitted prior context, and original request; distinguish accepted requirements from candidate prerequisites and unknowns. |
| Researcher | Sourced findings, candidate approaches, fixture setup requirements, verification criteria, contradictions, and unknowns; **not** an implementation plan or executed validation. |
| Audit POST | Map findings against a source checkpoint; preserve conflicting and irrelevant findings with reasons. No edits, architecture decisions, or final audit certification. |
| Planning | Review code, **plan** refactoring, resolve requirement/design gaps, define exact file actions and tests; Scanner detects gaps and returns findings to Planning. Planning does not edit source. |
| Fixture Validation | Validate the **build-and-test baseline** (required source, interfaces, dependencies, tools, assets, requirements, test setup, traceability) before approval; define chaos and recovery scenarios. Do not claim the completed program works or run future-product chaos tests before Build. |
| User Approval | Bind a verified plan revision, original source checkpoint, scope, dependencies, paths, actions, tools, and criteria; any material change requires renewed approval. |
| Builder | Prepare candidate changes and report them. Runtime controls task scheduling; Builder never grants permission or directly promotes final source. |
| Runtime Preflight / Sandbox | Before each effect, verify approval, source, paths, tools, authorization, and readiness; execute in isolation with attributable results and recoverable attempts. |
| Independent Validation | Test actual integrated behavior, acceptance, regressions, and applicable fault/recovery cases; verify against **original accepted intent** and trace each claim to evidence. |
| Completion | Host verifies receipts and reconcilable attempts; only then promote source and approved reusable knowledge. |

**No standalone `Package Lock`, `Build Admission`, or `Task Integration` stage.** An ordinary dependency lockfile (`uv.lock`, `web/package-lock.json`) is unrelated to the retired custom Package Lock **workflow concept** and must be retained. The existing Python `BuildAdmissionReceipt`, `PackageLockReceipt`, `EffectExecutor.execute_admitted()`, and corresponding workflow declarations are **legacy implementation dependencies pending tested migration**, not architectural requirements or permission to bypass a gate. Until migrated, fail closed on missing legacy receipts; preserve exact-scope authorization, tamper resistance, and effect-time checks.

**Prelight is NOT Preflight.** `memory_prelight` is the Host-frozen, hash-bound approved context immediately before Build; `memory_validation` is independently verified outcome knowledge promoted after successful verification. These are the two persistent **recallable** memory categories, not replacements for immutable artifact records, checkpoint/receipt stores, or `search.log`, `audit.log`, `plan.log`, `build.log`, and `mem.log`. Do not add a second orchestrator or standalone memory framework.

## Execution evidence and correction

Research and POST are not permission to build. Scanner assesses the **plan**, not finished behavior. Fixture Validation establishes whether the baseline is adequate, not whether the future implementation works. Preflight occurs before applying source effects. A Builder correction within the approved scope returns through Runtime checks and an isolated attempt; a scope or starting-checkpoint change returns to Planning and renewed approval. No separate Task Integration stage: integration and real E2E are independently verified; source promotion follows verification, never precedes it.

The standalone Modal Sandbox has a separate integration boundary and can return `result.json`, `after.tar`, `evidence.zip`, and attempt state. Such artifacts become verification evidence only after actually observed and independently assessed.

## Implementation status

- **Existing:** `agent/runtime/controller.py`, immutable artifacts/receipts/checkpoints, registered six-stage host lifecycle, Planner/Scanner contracts, `mvp/api.py`, and standalone `deployment/modal/sandbox_v3`.
- **Feature branch:** [draft PR #3](https://github.com/itz1508/OneShot-Continuing/pull/3) implements bounded PRE → MCP Research → POST persistence/lineage and opt-in frontend Auto Research with fixture-based tests. It does **not** prove a full live-model or Build-through-E2E run.
- **Drift to repair:** `.agents/contracts/workflow.yaml`, `agent/runtime/package_lock.py`, `agent/runtime/build_admission.py`, `agent/contracts/host.py`, `agent/runtime/effect_executor.py`, Build records, and related tests still depend on custom lock/admission receipts. Audit the complete consumer chain, migrate enforcement to Host approval + Preflight, demonstrate equivalent denial/recovery checks, then retire obsolete code. Do **not** merely delete files or weaken validations.
- **Not yet verified:** full repository-aware Audit POST, connected Planning/Scanner → Fixture baseline/chaos guidance → approval/Prelight → Builder/Preflight/Modal Sandbox → independent E2E → source promotion and memory retention.
- **Historical-only visuals:** [`docs/workflow.gif`](docs/workflow.gif) and [`docs/workflow.html`](docs/workflow.html) show an older illustrative diagram, not this authoritative workflow nor runtime evidence. [Audit history](audit/workflow-alignment-2026-11-05.md) is evidence of previous revisions, not the latest architecture decision.

## Get started

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js/npm. From the repository root:

```sh
uv sync --locked --extra meta --extra mvp
uv run --no-sync python -m agent doctor
uv run --no-sync uvicorn mvp.api:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
cd web
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. For MCP-backed Research, configure `ONESHOT_MCP_COMMAND` and `ONESHOT_MCP_ARGS_JSON` for stdio, or `ONESHOT_MCP_URL` for HTTP. See [Research integration](mvp/README.md#research-integration). Do not expose the development API publicly or commit credentials.

## Verification

```sh
uv lock --check
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy agent
uv run --no-sync pytest -q
```

Browser checks require Playwright Chromium:

```sh
cd web
npm ci
npx playwright install chromium
npm run build
npm run test:browser
```

Browser tests use deterministic MCP fixtures; they do not prove live-model operation. See [GitHub Actions](https://github.com/itz1508/OneShot-Continuing/actions) for recorded CI runs.

## Repository guide

[`AGENTS.md`](AGENTS.md) · [Workflow contract](.agents/contracts/workflow.yaml) · [`agent/contracts/`](agent/contracts/) · [`agent/runtime/`](agent/runtime/) · [`agent/audit/`](agent/audit/) · [`mvp/`](mvp/) · [`web/`](web/) · [`tests/`](tests/) · [`deployment/modal/`](deployment/modal/)

**Continuing repository:** [itz1508/OneShot-Continuing](https://github.com/itz1508/OneShot-Continuing) · `main`

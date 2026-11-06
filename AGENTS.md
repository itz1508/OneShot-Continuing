# OneShot — Repository Work Instructions

This file defines **standing work practices** for contributors and coding agents. It is not a task request, execution plan, runtime contract, permission grant, status report, or build log.

## Source of truth and workspace

- **`itz1508/OneShot-Continuing` on `main`** is the active repository. The imported `itz1508/OneShot` is provenance, not a push target. Do not assume a fixed local checkout path. Check `git status` and `git log` before making changes.
- Use Python **3.11+**, Pydantic **v2**, and **uv**. `pyproject.toml` declares dependencies; `uv.lock` records the resolution.
- `settings/config.yaml` is the runtime/provider configuration. Validate against implemented schemas; do not invent settings.
- Meta Muse Spark 1.3 is the configured **default** provider. Claude Agent SDK and Codex SDK are **optional** adapters.
- The `echo` provider is a test double only — never the runtime default.

## Commands and dependency conventions

| Task | Convention |
| --- | --- |
| Check Python | `uv run --no-sync python --version` |
| Check lock | `uv lock --check` |
| Sync baseline + Meta | `uv sync --locked --extra meta` |
| Run tests | `uv run --no-sync pytest -q` |
| Lint | `uv run --no-sync ruff check .` |
| Format check | `uv run --no-sync ruff format --check .` |
| Type check | `uv run --no-sync mypy agent` |
| Check environment | `uv run --no-sync python scripts/doctor.py` |
| CLI | `uv run --no-sync python -m agent doctor` |

## Current architectural decision (2026-11-06)

**Read the current workflow in [README.md](README.md) before using any old Plan, workflow GIF, source-import documentation, or Library history.** Prior `Package Lock` / `Build Admission` stage proposals, duplicated orchestrator proposals, and an Audit PRE/POST source-editing role are **superseded**. Historic code and receipts still exist until a separately verified migration removes their dependencies; never bypass current runtime denial checks. `uv.lock` and `web/package-lock.json` remain standard dependency lockfiles.

Runtime/Controller owns the whole workflow and every return; Planning only **plans** refactoring; Fixture Validation checks complete build baseline readiness and defines chaos scenarios, while executable chaos runs after Build; Builder prepares candidate changes, Runtime manages Preflight, Sandbox and source effects; independent E2E precedes source promotion. `memory_prelight` is immutable approved context, not Preflight or an extra stage.

## How to perform authorized work

1. **Establish scope** before modifying. Inspect `git status`, relevant code, and contracts.
2. **Research** establishes evidence, not implementation design.
3. **Audit Discovery** is read-only. Record grounded findings and candidate CodeIntent.
4. **Planning** owns architecture, design decisions, and BuildSpecification. No source writes.
5. **Approval and execution readiness** are host-owned. The host binds the exact plan revision and source checkpoint, validates baseline readiness, and runs Preflight.
6. **Build** executes only user-approved, Host-authorized operations. Check preconditions at effect time.
7. **Independent verification** runs real E2E checks against accepted criteria.

## Responsibility boundaries

- **Researcher:** requirements, evidence, acceptance criteria. No final design.
- **Audit Discovery:** read-only findings, CodeIntent. No Build dispatch.
- **Planner:** design and refactoring PLAN, BuildSpec, Scanner requests. No source edits or self-authorization.
- **Fixture Validator:** baseline files/dependencies/configuration/assets/criteria readiness; define chaos cases for later execution. No plan mutation.
- **Builder:** candidates and TaskTodo reports within exact approved scope. No self-authorization, direct source promotion, or scope expansion.
- **Build Verifier:** independent E2E. No self-certification.
- **Host:** transitions, routing, approval, Prelight, authorization, Preflight, sandbox effects, persistence, receipts, and recovery.

Authorization is **default-deny and host-enforced**. Every effect requires a host gate.

## Security and completion

- Keep secrets in environment variables, never in Git. Commit only `.env.example` placeholders.
- Use minimal changes. Preserve working tests. Never weaken assertions to make checks pass.
- If a check is unavailable, mark it **not checked** or **blocked**, not passed.

## Tool provenance and structural readiness

- Preserve the existing `ToolRegistrySnapshot` and typed `ToolInvocation(tool_id, args)` discipline; never convert prose into shell commands.
- Runtime validates actual executable/tool identity, path scope, source preimages, sandbox profile, approved actions, and receipts **at effect time**, using existing stores and deny-by-default authorization.
- The custom `Package Lock` and `Build Admission` gates in the current implementation are **legacy migration dependencies**, not desired workflow stages. Do not delete/bypass their safety checks until the same refusal, lineage, crash/recovery, and execution controls are verified through the approved Runtime + Preflight path.
- Do not invent new `approval.py`, `preflight.py`, `sandbox_gateway.py`, or an alternate `orchestrator.py` unless a source audit proves a concrete missing contract and the Planner owns an admitted file action.
- Do not treat historic `/Plan-Build-log/` plans (ChatGPT Library, **not repository source**) as current architecture. The latest explicit user decision and current `README.md` supersede obsolete proposals.

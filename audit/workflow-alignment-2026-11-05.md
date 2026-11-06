# OneShot-Continuing — Workflow Implementation and Terminology Audit

**One-line finding:** The intended workflow is documented; a full connected Discovery-to-Completion runtime is not yet verified.

- **Source checkpoint reviewed:** `a2c29610448a753d4ceac3da20254eca63aee30a` on `main`.
- **Recorded:** 2026-11-05T04:45:37-08:00.
- **Method:** Repository source inspection, comparison with imported continuation baseline, and GitHub Actions job results. No local checkout or new E2E run was available. No production source or workflow contract was changed.
- **Separation:** A source-defined component, a declared contract, a fixture test, and a connected operational run are different kinds of evidence.

## What is done

| Component | Evidence-grounded finding |
| --- | --- |
| Provenance | `CONTINUATION.md` identifies the detached snapshot of OneShot `7816222`, imported at `100365f`. |
| Host foundation | `agent/runtime/controller.py` has six role-stage enums, receipt/To-Do checks and CAS checkpoints. This is source presence, not a complete hosted orchestration. |
| Research | `mvp/api.py` has `POST /api/tasks/{task_id}/research`; the persisted MCP Research path is present. |
| Catalog | `agent/research_catalog.py` and `agent/runtime/research_lifecycle.py` implement a versioned synthetic Catalog matched to Research inputs. Discovery is not an evidenced second runtime consumer. |
| Read-only Audit | `mvp/api.py` has `POST /api/tasks/{task_id}/audit`; `mvp/service.py` treats it as separate purpose while the task remains in Research. |
| Planning/Scanner foundations | `agent/contracts/planning.py` defines `BuildSpecification` and eight Planning issue types. `agent/contracts/scanner.py` declares six different technical capabilities, and `agent/runtime/scanner_gateway.py` accepts registered detectors. Full eight-type automated coverage is not established. |
| Build foundations | `agent/runtime/build_admission.py` issues the internal authorization receipt; `agent/runtime/effect_executor.py` implements bounded effects. `deployment/modal/sandbox_v3` is a standalone Sandbox package with its own tests. |
| Test evidence | `tests/e2e/test_real_workflow.py` exercises host stages/security with temporary workspaces and explicit receipts, not an integrated external-agent run. [CI 42027538233](https://github.com/itz1508/OneShot-Continuing/actions/runs/42027538233) succeeded for Python 3.11/3.12 at the audited SHA. Earlier [MVP](https://github.com/itz1508/OneShot-Continuing/actions/runs/41978409774) and [Research/Audit](https://github.com/itz1508/OneShot-Continuing/actions/runs/41978409723) jobs succeeded at `1280f06`. |
| New continuation work | `15303a9`: configured model API metadata in `web/src/main.jsx` and connector tests. `52dc3a1`: video evidence guide. Later commits culminate in README + animated GIF + HTML viewer at `a2c2961`. No new full-workflow engine was introduced by those changes. |

## Remaining work, in dependency order

| Priority | Requirement | Evidence needed to close |
| --- | --- | --- |
| 1 | Discovery request generation and fixture guidance; Catalog must supply both Discovery and Research. | Registered producer/consumers, tested request identities and guidance lineage. |
| 2 | Research evidence handed to Repository Audit, including Audit-scoped Research follow-ups. | Verified Research artifact/receipt/source checkpoint and connected audit transition. |
| 3 | Planning-owned implementation design, gap resolution, and **Scanner as its final step**. | Candidate-specific scanner results, revised plans and repeatable checks across eight `PlanningIssue` types. |
| 4 | User Review and Approval bound to exact plan revision and **starting** source checkpoint. | Persisted review decision and authorization refusal/renewal cases. Approved Build changes must not invalidate that starting checkpoint. |
| 5 | Builder tasks plus Preflight for scope, preimages, dependencies, tools and executable Sandbox readiness. | Exact approved task list; denial before Sandbox when prerequisites are unresolved. |
| 6 | Host-controlled one-attempt-per-Sandbox execution, integration and recovery. | Connected Modal attempt exporting `result.json`, `after.tar`, `evidence.zip`, attempt state and verified source delta. |
| 7 | Independent Validation, source promotion, cleanup and retention. | Real entrypoint/E2E checks on resulting source, baseline vs introduced failures, trusted receipts and reconciled attempts. |
| 8 | Optional Call for Help diagnostic hook, without model switch. | Connected scoped diagnostic request keeping original task, role, provider and model identity. |

## Naming and responsibility boundary

| User-facing term | Registered/internal counterpart |
| --- | --- |
| OneShot-Continuing | Active repository; OneShot is imported product/source provenance. |
| Catalog and Template Selection | Supporting Catalog service; `ResearchCatalog` contract unchanged. |
| Discovery | Request preparation; **not** separately implemented as first host stage. |
| Repository Audit | Read-only repository inspection, distinct from full `audit_discovery` role and current MVP `purpose=audit`. |
| Planning; Scanner at the end | Planner owns correction and design; `scanner_execution` is host-dispatched, not a new top-level role. |
| User Review and Approval | Proposed exact-revision/source-checkpoint binding. |
| Build Authorization | Public label for internal `build_admission`; do not rename its code/API identifier without migration. |
| Builder → Preflight → Sandbox Execution | Internal parts of the Build phase, not separate autonomous top-level roles. |
| Independent Validation | Intended user-facing `build_validation` responsibility. |
| Completion and Retention | Final verification, reconciliation, cleanup and trusted-artifact promotion. |

**Scanner scope:** The eight Planning issue types are compatibility, dependency, interface, concurrency, security, recovery, buildability and verifiability. Overlap, duplication, ownership drift and missing contracts are cross-cutting structural findings, not extra top-level stages. Scanner reports findings; Planning resolves them.

**Status:** Presentation and naming have documentation-level corrections only. The connected workflow is **not READY** on this evidence. CI success verifies the configured checks, not an actual full workflow run.

## 2026-11-05T19:10:17-08:00 — Evidence update (append-only)

**One-line finding:** Discovery PRE → MCP Research → Discovery POST is now implemented and fixture-tested on the Continuing feature branch; the complete Build workflow is still unverified.

- **Source:** [draft PR #3](https://github.com/itz1508/OneShot-Continuing/pull/3); original Continuing checkpoint `13720b7495d2ef86897ad9f13046b563c0969c5f`.
- **Changed runtime:** PRE prepares synthetic Catalog-guided questions and a verified Research request from user intent and generated message ID. Existing Host dispatch and Research execution remain authority. POST ingests Research claims without planning or action selection; Host Audit transition requires matching PRE/POST artifacts and stable observations.
- **Current limitations:** Source observation is bounded; summary is extractive; POST is not the canonical Audit Discovery codebase assessment; scanning memory/thread history is unimplemented. Scanner remains under Planning and does not itself authorize Build.
- **Validation:** CI Python, Host integrity, MVP backend/frontend and Research/Audit checks confirmed successful at the code revisions above. The Chromium fixture-based browser scenario is separately pending and cannot be claimed verified. This does not establish complete Build-through-independent-E2E readiness.

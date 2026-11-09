# OneShot-Continuing: Host, Runtime and Audit relocation

**Scope:** Structural relocation only. The workflow order and Host authorization semantics are unchanged.

## Canonical ownership

- `system/host/controller.py` — sole workflow transition authority.
- `system/host/authorization.py` — default-deny authorization.
- `system/host/guardrails.py` — blocking guardrails.
- `system/runtime/artifact_store/store.py` — immutable artifacts.
- `system/runtime/checkpoint_store/store.py` — durable checkpoints and CAS.
- `system/runtime/event_store/store.py` — append-only events.
- `system/runtime/receipt_store/store.py` — Host-only receipts.
- `system/runtime/execution/executor.py` — authorized execution and recovery.
- `agent/skills/auditor/` — the existing read-only Audit implementation.

All legacy `agent/runtime/{controller,authorization,guardrails,artifact_store,checkpoint_store,event_store,receipt_store,effect_executor}.py` and `agent/audit/*.py` modules now expose compatibility imports only, not competing implementations. Transition consumers and tests to canonical paths before removing adapters.

## Not implemented by this move

The full Discovery/Audit PRE → Research → Audit POST → Planning → Fixture/Chaos definition → Approval → memory_prelight → Builder/Preflight/Sandbox → Independent E2E/Chaos → memory_validation target remains future work. Do not invent role handlers, direct skill execution authority, approval receipts or E2E evidence.

## Validation to run on the exact branch

```sh
uv sync --locked --extra meta --extra mvp
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy agent system
uv run --no-sync pytest -q
uv run --no-sync python -m agent doctor
uv run --no-sync python -m system.host doctor
```

The `__main__.py` modules in individual Runtime stores are read-only informational entry points, never new execution or authorization services.

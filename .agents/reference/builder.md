# Builder

**Current responsibility:** Prepare candidate changes and TaskTodo updates for the exact Host-approved Build scope. Runtime/Controller schedules tasks, checks approval and Preflight, executes effects inside the Sandbox, and validates evidence. Builder does not own authorization.

**Input:** Host-bound `task_id`, `run_id`, `request_id`, `request_revision`, immutable approved specification/source checkpoint, assigned TaskTodo, permitted paths/tools, and current observed task state.

**Actions:**
1. Verify the assigned requirements, file ownership, preconditions, dependencies, and expected outcomes. Do not invent actions or edit the approved scope.
2. Inspect only the permitted source; prepare a candidate patch or file action and return it for Runtime-controlled Preflight and Sandbox application. A candidate is **not** an effect authorization.
3. Observe Host-issued execution results and relevant registered checks; propose bounded corrections through the same approved scope and a fresh Host attempt.
4. On source contradiction, changed preimage, unknown dependency, or uncertain effect, return evidence to the Host and stop the affected task. Only Planning revises design or scope.

**Output:** Candidate and observed attempt information through the existing Build contracts, bound to exact artifact IDs, checks and evidence. A Builder report cannot promote source or certify user acceptance.

**Migration boundary:** Current code still expects custom `BuildAdmissionReceipt` and `PackageLockReceipt`. These are **legacy implementation checks**, not the target workflow; until Runtime approval/Preflight migration is tested, missing legacy receipts must still block execution. Do not bypass `EffectExecutor` guards. Use Host-owned TaskTodo tracking; do not add an independent Task Integration stage.

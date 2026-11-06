/* OneShot interactive demo — deterministic simulated playback engine.
   CLASSIFICATION: every workflow event rendered here is SIMULATED fixture data.
   No real OneShot backend is called by this page. Real-backend captures live in
   screenshots/reference/. Scenario definitions are loaded from scenarios.json. */
'use strict';
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const titleize = (v) => String(v || '').replaceAll('_', ' ').replace(/\b\w/g, (m) => m.toUpperCase());

const STAGES = ['Intake', 'Research', 'Audit', 'Planning', 'Fixture Validation', 'Build Admission', 'Build', 'Verification'];
const TASK_ID = 'a3f9c1e84b2d4f6a9e0c5b7d1a2f3e4c';

const state = {
  scenarios: [], scenario: null, step: 0, playing: false, playAll: false,
  task: null, events: [], artifacts: [], todos: [], seq: 0, stageState: {},
  execution: 'idle', capability: 'Research', admitted: false, mcp: false, model: false,
};

/* ---------- deterministic fixtures ---------- */
const ARTIFACT_CONTENT = {
  'task_input.md': (s) => `# Task input · rev ${s.artifacts.find(a => a.name === 'task_input.md')?.rev || 1}\n\n${s.task.prompt}\n\nCapability: ${s.task.purpose}\nTask: ${TASK_ID}`,
  'task_research.json': () => JSON.stringify({ task_id: TASK_ID, kind: 'research', findings: [
    { area: 'providers', file: 'agent/providers.py', note: 'Meta Muse Spark 1.3 default; Claude/Codex optional adapters' },
    { area: 'host gates', file: 'agent/host.py', note: 'Authorization default-deny; host owns freeze + admission' },
    { area: 'tool registry', file: 'agent/tools.py', note: 'Pinned ToolRegistrySnapshot with SHA-256 digests' },
    { area: 'config', file: 'settings/config.yaml', note: 'Runtime config validated against implemented schemas' }],
    acceptance: ['Evidence cites real files', 'No invented settings', 'Echo provider never runtime default'] }, null, 2),
  'task_audit.json': () => JSON.stringify({ task_id: TASK_ID, kind: 'audit', read_only: true, findings: [
    { code: 'shell_execution_surface', severity: 'high', path: 'agent/tools.py', line: 142, message: 'Tool resolution must return argv without a shell; verify no shell=true path remains.' },
    { code: 'secret_handling', severity: 'medium', path: 'agent/providers.py', line: 88, message: 'Provider errors must redact API keys before reaching the event stream.' },
    { code: 'error_detail_loss', severity: 'low', path: 'agent/host.py', line: 231, message: 'Blocked transitions lose the gate detail in the persisted event message.' }],
    code_intent: ['CI-1 sandbox argv enforcement', 'CI-2 secret redaction', 'CI-3 gate detail preservation'] }, null, 2),
  'build_spec.json': (s) => JSON.stringify({ task_id: TASK_ID, frozen_by: 'host', revision: s.artifacts.find(a => a.name === 'build_spec.json')?.rev || 1, actions: [
    { id: 'TODO-1', tool: 'sandbox.exec', change: 'Enforce argv-without-shell tool execution', digest: 'sha256:7be1…c204' },
    { id: 'TODO-2', tool: 'fs.patch', change: 'Redact provider secrets in error events', digest: 'sha256:41ad…90fe' },
    { id: 'TODO-3', tool: 'registry.pin', change: 'Pin tool digest from ToolRegistrySnapshot', digest: 'sha256:9f2c…e41a' },
    { id: 'TODO-4', tool: 'fs.patch', change: 'Preserve gate detail + completed_at ordering', digest: 'sha256:d812…77b3' }],
    acceptance: ['uv run pytest -q', 'ruff check .', 'mypy agent'] }, null, 2),
  'fixture_report.json': (s) => JSON.stringify({ task_id: TASK_ID, verdict: s.stageState['Fixture Validation'] === 'done' ? 'passed' : 'rejected',
    checks: [{ name: 'producer/consumer closure', result: 'pass' }, { name: 'stage effect gates', result: 'pass' },
      { name: 'tool provenance (TODO-3)', result: s.stageState['Fixture Validation'] === 'done' ? 'pass' : 'fail — digest missing from ToolRegistrySnapshot' }],
    note: 'Missing provenance is a blocker, not an implicit external dependency.' }, null, 2),
  'admission_receipt.json': () => JSON.stringify({ task_id: TASK_ID, issued_by: 'host', admitted_actions: ['TODO-1', 'TODO-2', 'TODO-3', 'TODO-4'],
    tool_ids: ['sandbox.exec', 'fs.patch', 'registry.pin'], sandbox_profile: 'pinned-default', authorization: 'host gate passed (default-deny evaluated)' }, null, 2),
  'build_result.json': () => JSON.stringify({ task_id: TASK_ID, result: '4/4 actions succeeded', receipts: [
    { id: 'TODO-1', tool: 'sandbox.exec', digest_recheck: 'ok' }, { id: 'TODO-2', tool: 'fs.patch', digest_recheck: 'ok' },
    { id: 'TODO-3', tool: 'registry.pin', digest: 'sha256:9f2c…e41a' }, { id: 'TODO-4', tool: 'fs.patch', digest_recheck: 'ok' }] }, null, 2),
  'verification_report.json': () => JSON.stringify({ task_id: TASK_ID, verifier: 'independent (not the builder)', criteria: [
    { name: 'Sandbox argv contains no shell', result: 'pass' }, { name: 'Tool digest rechecked pre-execution', result: 'pass' },
    { name: 'Secrets redacted in event stream', result: 'pass' }, { name: 'Admitted actions only — no scope expansion', result: 'pass' },
    { name: 'Event ordering by sequence', result: 'pass (after replay re-run)' }, { name: 'Artifacts persisted with revisions', result: 'pass' }], verdict: '6/6 passed' }, null, 2),
  'task_summary.json': () => JSON.stringify({ task_id: TASK_ID, status: 'completed_verified', stages: STAGES.map((n) => ({ stage: n, result: 'done' })),
    artifacts: ['task_input.md', 'task_research.json', 'task_audit.json', 'build_spec.json', 'fixture_report.json', 'admission_receipt.json', 'build_result.json', 'verification_report.json'],
    verification: '6/6 acceptance criteria passed (independent verifier)' }, null, 2),
};
const FINDING_CHIPS = ['agent/providers.py', 'agent/host.py', 'agent/tools.py', 'settings/config.yaml'];

/* ---------- rendering helpers ---------- */
const transcript = () => $('#transcript');
function scrollEnd() { const t = transcript(); t.scrollTop = t.scrollHeight; }
function botSvg(st) {
  return `<svg class="bot" data-state="${st}" viewBox="0 0 120 110" aria-hidden="true"><line x1="60" y1="8" x2="60" y2="22" stroke="#cfdcff" stroke-width="3" stroke-linecap="round"/><circle class="tip" cx="60" cy="7" r="4"/><rect class="ear" x="6" y="44" width="12" height="16" rx="6"/><rect class="ear" x="102" y="44" width="12" height="16" rx="6"/><rect class="head" x="22" y="24" width="76" height="56" rx="24"/><rect class="visor" x="33" y="36" width="54" height="32" rx="16"/><circle class="eye" cx="50" cy="52" r="4.5"/><circle class="eye" cx="70" cy="52" r="4.5"/><rect class="body" x="38" y="86" width="44" height="20" rx="10"/></svg>`;
}
function emptyState() {
  transcript().innerHTML = `<div class="empty-state">${botSvg('idle')}<h2>What should OneShot look into?</h2><p>It reads through your workspace and tells you what needs attention.</p></div>`;
}
function addMsg({ side = 'agent', sender = 'OneShot', label = 'SIMULATED', body = '', tone = '', chips = [], findings = [], bot = '' }) {
  const t = transcript();
  t.querySelector('.empty-state')?.remove();
  const el = document.createElement('div');
  el.className = 'msg ' + (side === 'user' ? 'user' : 'agent ' + tone);
  el.dataset.sim = 'true';
  const chipHtml = chips.length ? `<div class="chips">${chips.map((c) => `<span class="chip">${esc(c)}</span>`).join('')}</div>` : '';
  const findHtml = findings.map((f) => `<div class="finding"><b class="sev-${f.severity}">${esc(f.code)}</b> · <span class="sev-${f.severity}">${esc(f.severity)}</span><div>${esc(f.message)}</div><div class="where">▸ ${esc(f.path)}${f.line ? ':' + f.line : ''}</div></div>`).join('');
  el.innerHTML = side === 'user'
    ? `<div class="msg-body">${esc(body)}</div>`
    : `<div class="msg-meta">${bot}<strong>${esc(sender)}</strong><span>${esc(label)}</span><span class="chip warn" style="margin-left:auto">SIMULATED</span></div><div class="msg-body">${body.split('\n').map((l) => `<p>${esc(l) || '&nbsp;'}</p>`).join('')}</div>${findHtml}${chipHtml}`;
  t.appendChild(el); scrollEnd();
  return el;
}
async function streamMsg(opts, fullText) {
  const el = addMsg({ ...opts, body: '', bot: `<span class="typing"><i></i><i></i><i></i></span>` });
  const bodyEl = el.querySelector('.msg-body');
  await sleep(650);
  const words = fullText.split(' ');
  for (let i = 0; i < words.length; i += 3) {
    bodyEl.innerHTML = `<p>${esc(words.slice(0, i + 3).join(' '))}</p>`; scrollEnd();
    await sleep(40);
  }
  el.querySelector('.typing')?.remove();
  return el;
}
function addEvent(type, message) {
  state.seq += 1;
  state.events.push({ sequence: state.seq, type, message });
  if (state.events.length > 40) state.events.shift();
  renderEvents();
}
function renderEvents() {
  const list = $('#eventList');
  const count = state.events.length;
  $('#eventCount').textContent = count + ' events';
  $('#eventCount2').textContent = count + ' events';
  list.innerHTML = count
    ? state.events.slice(-8).reverse().map((e) => `<div class="event-row"><span class="event-seq">#${e.sequence}</span><div><strong>${esc(titleize(e.type))}</strong><p>${esc(e.message)}</p></div></div>`).join('')
    : '<div class="empty-note">Live host events will appear here.</div>';
}
function renderArtifacts() {
  const list = $('#artifactList');
  const count = state.artifacts.length;
  $('#artifactCount').textContent = count + ' artifacts';
  $('#artifactCount2').textContent = count + ' files';
  list.innerHTML = count
    ? state.artifacts.slice().reverse().slice(0, 8).map((f) => `<button type="button" class="artifact-row" data-name="${esc(f.name)}"><span>▤</span><span><strong>${esc(f.name)}</strong><small>${f.kind === 'input' ? 'Editable input' : 'Read-only artifact'} · rev ${f.rev}</small></span><span class="chev">›</span></button>`).join('')
    : '<div class="empty-note">Artifact snapshots appear here after the host persists them.</div>';
  list.querySelectorAll('.artifact-row').forEach((b) => b.addEventListener('click', () => openArtifact(b.dataset.name)));
}
function addArtifact(name, kind = 'artifact', rev = 1) {
  const existing = state.artifacts.find((a) => a.name === name);
  if (existing) existing.rev = rev; else state.artifacts.push({ name, kind, rev });
  renderArtifacts();
}
function renderStages() {
  $('#stageBar').innerHTML = STAGES.map((name) => {
    const st = state.stageState[name] || 'pending';
    const icon = st === 'done' ? '✓ ' : st === 'active' ? '◌ ' : st === 'failed' ? '✕ ' : st === 'blocked' ? '⛔ ' : '';
    return `<div class="stage-chip ${st}" data-stage="${esc(name)}"><b>${icon}${esc(name)}</b><span>${esc(st)}</span></div>`;
  }).join('');
}
function setStage(name, st) { state.stageState[name] = st; renderStages(); }
function setExecution(v, stageLabel) {
  state.execution = v;
  $('#statExecution').textContent = v;
  if (stageLabel) $('#statStage').textContent = stageLabel;
}
function setProgress(pct, label, failed = false) {
  $('#progressWrap').hidden = false;
  $('#progressFill').style.width = pct + '%';
  $('#progressFill').classList.toggle('failed', failed);
  $('#progressPct').textContent = pct + '%';
  if (label) $('#progressLabel').textContent = label;
}
function renderTodos() {
  $('#todoBlock').hidden = state.todos.length === 0;
  $('#todoCount').textContent = state.todos.length + ' items';
  $('#todoList').innerHTML = state.todos.map((t) => `<div class="todo-row ${t.status}" data-todo="${esc(t.id)}"><span class="box">${t.status === 'done' ? '✓' : t.status === 'failed' ? '✕' : t.status === 'doing' ? '◌' : ''}</span><span class="todo-text">${esc(t.text)}<small>${esc(t.id)} · ${esc(t.tool)}</small></span></div>`).join('');
}
function setTodo(id, status) { const t = state.todos.find((x) => x.id === id); if (t) { t.status = status; renderTodos(); } }
function toast(text, kind = '') {
  const el = $('#toast');
  el.textContent = text; el.className = 'toast ' + kind; el.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { el.hidden = true; }, 4200);
}
function showAlert(text) { $('#alertText').textContent = text; $('#alertBox').hidden = false; }
function hideAlert() { $('#alertBox').hidden = true; }
function openArtifact(name) {
  const file = state.artifacts.find((a) => a.name === name);
  if (!file) { toast('Artifact not available yet: ' + name, 'warn'); return; }
  $('#modalFileName').textContent = name;
  $('#modalFileRev').textContent = 'rev ' + file.rev;
  $('#modalMeta').textContent = file.kind === 'input' ? 'Editable input with revision checks · SIMULATED' : 'Read-only artifact · SIMULATED';
  const gen = ARTIFACT_CONTENT[name];
  $('#file-editor').value = gen ? gen(state) : '(no preview fixture)';
  $('#artifactModal').hidden = false;
}
function closeArtifact() { $('#artifactModal').hidden = true; }
const MCP_TOOLS = [
  { name: 'oneshot_research', description: 'Research tool' },
  { name: 'source_lookup', description: 'Lookup source data' },
];
const CONNECTOR_DEFAULT_MESSAGE = 'Changes are saved locally in this browser only for non-sensitive fields.';
function setConnectorMessage(text) { $('#connectorMessage').textContent = text || CONNECTOR_DEFAULT_MESSAGE; }
function renderMcpTools(tools = []) {
  $('#mcpTools').innerHTML = tools.length
    ? tools.map((tool) => `<div class="tool-item"><strong>${esc(tool.name)}</strong><span>${esc(tool.description)}</span></div>`).join('')
    : '<div class="empty-note">No tools discovered yet.</div>';
}
function syncMcpAuthField() {
  const bearer = $('#mcpAuthType').value === 'bearer';
  $('#mcpToken').hidden = !bearer;
  $('#mcpTokenLabel').hidden = !bearer;
}
function setMcpStatus(status, error = '') {
  state.mcp = status === 'connected';
  $('#mcpStatus').textContent = status;
  const chip = $('#mcpStateChip');
  chip.className = 'status-chip' + (status === 'connected' ? ' live' : error ? ' bad' : ' muted');
  const errorEl = $('#mcpError');
  errorEl.hidden = !error;
  errorEl.textContent = error;
  if (status === 'connected') renderMcpTools(MCP_TOOLS);
  if (status === 'disconnected') renderMcpTools([]);
  const pill = $('#mcpPill');
  pill.className = 'conn' + (state.mcp ? '' : error ? ' bad' : ' warn');
  pill.querySelector('span').textContent = state.mcp ? 'MCP connected' : 'MCP disconnected';
}
function setModelStatus(status, error = '', response = '') {
  state.model = status === 'connected' || status === 'saved';
  $('#modelStatus').textContent = status;
  const chip = $('#modelStateChip');
  chip.className = 'status-chip' + (status === 'connected' || status === 'saved' ? ' live' : error ? ' bad' : ' muted');
  const errorEl = $('#modelError');
  errorEl.hidden = !error;
  errorEl.textContent = error;
  const responseEl = $('#modelResponse');
  responseEl.hidden = !response;
  responseEl.textContent = response ? 'Provider response: ' + response : '';
  const pill = $('#modelPill');
  pill.className = 'conn' + (status === 'connected' ? '' : status === 'saved' ? '' : error ? ' bad' : ' warn');
  pill.querySelector('span').textContent = status === 'connected' ? 'Model connected' : status === 'saved' ? 'Model settings saved' : 'Model disconnected';
}
function resetConnectors() {
  $('#settingsModal').hidden = true;
  $('#mcpUrl').value = '';
  $('#mcpAuthType').value = 'none';
  $('#mcpToken').value = '';
  $('#modelBaseUrl').value = '';
  $('#modelId').value = '';
  $('#modelKey').value = '';
  syncMcpAuthField();
  setMcpStatus('disconnected');
  setModelStatus('disconnected');
  $('#savedModelId').textContent = 'No model selected';
  $('#savedModelUrl').textContent = 'No base URL configured';
  setConnectorMessage(CONNECTOR_DEFAULT_MESSAGE);
}

/* ---------- shared workflow prerequisites (state builders) ---------- */
function ensureTask(promptText, purpose) {
  if (state.task) return;
  state.task = { task_id: TASK_ID, prompt: promptText, purpose };
  state.capability = titleize(purpose);
  setStage('Intake', 'done');
  setExecution('awaiting_mcp', 'Intake');
  $('#topTaskTitle').textContent = 'Host-backed workflow';
  $('#topTaskId').textContent = 'Task ' + TASK_ID.slice(0, 8) + '…';
  $('#summaryTitle').textContent = 'Host-backed workflow';
  $('#statTaskId').textContent = TASK_ID.slice(0, 8) + '…';
  $('#statCapability').textContent = state.capability;
  $('#nextAction').textContent = 'The host froze the submitted input. Run the selected capability when ready.';
  addArtifact('task_input.md', 'input', 1);
  addEvent('task_created', 'Host created task ' + TASK_ID.slice(0, 8) + '… and froze the submitted input (rev 1).');
  const run = $('#runBtn');
  run.disabled = false;
  run.textContent = 'Run ' + state.capability;
  $('#runHelp').textContent = 'This calls the simulated host action for this demo.';
}
async function ensureResearch(fromAudit) {
  ensureTask('Research the OneShot repository: map the agent package, providers, and host gates', 'research');
  if (state.stageState['Research'] === 'done') return;
  setStage('Research', 'active'); setExecution('running', 'Research');
  await streamMsg({ sender: 'Researcher', label: 'MCP worker · SIMULATED', tone: 'host' },
    'Research complete. I mapped the agent package, the provider adapters, and the host gate model. Four evidence findings are pinned to real files; the echo provider is confirmed as a test double only, never the runtime default.');
  addMsg({ sender: 'Researcher', label: 'Evidence', tone: 'host', body: 'Evidence pinned to repository files:', chips: FINDING_CHIPS });
  addEvent('research_evidence', '4 findings pinned: providers.py, host.py, tools.py, config.yaml.');
  addArtifact('task_research.json', 'artifact', 1);
  addEvent('research_completed', 'Researcher persisted task_research.json rev 1.');
  setStage('Research', 'done'); setExecution('research_completed', 'Audit Discovery');
  if (!fromAudit) $('#nextAction').textContent = 'Research persisted. Continue with Audit Discovery or open the evidence artifact.';
}
function auditFindings() {
  return JSON.parse(ARTIFACT_CONTENT['task_audit.json']()).findings;
}
async function ensureAudit() {
  await ensureResearch(true);
  if (state.stageState['Audit'] === 'done') return;
  setStage('Audit', 'active'); setExecution('running', 'Audit Discovery');
  await streamMsg({ sender: 'Audit Discovery', label: 'read-only · SIMULATED', tone: 'host' },
    'Read-only inspection finished. I checked tool execution, provider secret handling, and host gate errors. Three candidate findings recorded — no source was modified.');
  addMsg({ sender: 'Audit Discovery', label: 'Findings', tone: 'warn', body: 'Candidate findings (confirmed status in task_audit.json):', findings: auditFindings() });
  addEvent('audit_finding', '3 findings: 1 high, 1 medium, 1 low.');
  addArtifact('task_audit.json', 'artifact', 1);
  addEvent('audit_completed', 'Audit Discovery persisted task_audit.json rev 1 (read-only).');
  setStage('Audit', 'done'); setExecution('audit_completed', 'Planning');
}
const TODO_DEFS = [
  { id: 'TODO-1', text: 'Enforce argv-without-shell tool execution', tool: 'sandbox.exec' },
  { id: 'TODO-2', text: 'Redact provider secrets in error events', tool: 'fs.patch' },
  { id: 'TODO-3', text: 'Pin tool digest from ToolRegistrySnapshot', tool: 'registry.pin' },
  { id: 'TODO-4', text: 'Preserve gate detail + completed_at ordering', tool: 'fs.patch' },
];
async function ensurePlan() {
  await ensureAudit();
  if (state.stageState['Planning'] === 'done') return;
  setStage('Planning', 'active'); setExecution('planning', 'Planning');
  await streamMsg({ sender: 'Planner', label: 'SIMULATED' },
    'I converted the audit CodeIntent candidates into a BuildSpecification with four typed TODOs. I draft the spec — the host alone freezes it.');
  state.todos = TODO_DEFS.map((t) => ({ ...t, status: 'pending' }));
  renderTodos();
  addEvent('plan_created', 'Planner drafted BuildSpec with 4 TODOs.');
  addMsg({ sender: 'Host', label: 'freeze · SIMULATED', tone: 'host', body: 'BuildSpecification frozen by the host as build_spec.json rev 1.\nPlanner cannot freeze or admit its own spec.' });
  addArtifact('build_spec.json', 'artifact', 1);
  addEvent('spec_frozen', 'Host froze build_spec.json rev 1.');
  setStage('Planning', 'done'); setExecution('spec_frozen', 'Fixture Validation');
  $('#nextAction').textContent = 'BuildSpec frozen as build_spec.json. Next: independent fixture validation.';
}
async function ensureValidated() {
  await ensurePlan();
  if (state.stageState['Fixture Validation'] === 'done') return;
  setStage('Fixture Validation', 'blocked'); setTodo('TODO-3', 'failed');
  showAlert('Fixture validation rejected: TODO-3 tool digest is missing from the ToolRegistrySnapshot. Missing provenance is a blocker.');
  addArtifact('fixture_report.json', 'artifact', 1);
  addEvent('validation_rejected', 'Fixture Validator rejected the spec: digest provenance missing for TODO-3.');
  await streamMsg({ sender: 'Planner', label: 'correction · SIMULATED' },
    'Correcting the spec: I pinned digest sha256:9f2c…e41a for registry.pin from the host ToolRegistrySnapshot. The host re-freezes the spec as rev 2.');
  addArtifact('build_spec.json', 'artifact', 2);
  addEvent('spec_corrected', 'build_spec.json rev 2 frozen with pinned digest sha256:9f2c…e41a.');
  hideAlert(); setTodo('TODO-3', 'pending');
  addMsg({ sender: 'Fixture Validator', label: 'independent · SIMULATED', tone: 'host', body: 'Re-validation passed. Producer/consumer closure, stage effect gates, and tool provenance all check out against the frozen rev 2 spec.' });
  addArtifact('fixture_report.json', 'artifact', 2);
  addEvent('validation_passed', 'Fixture Validator passed build_spec.json rev 2.');
  setStage('Fixture Validation', 'done'); setExecution('validated', 'Build Admission');
  $('#nextAction').textContent = 'Validation passed. Next: host Build Admission (default-deny).';
}
async function ensureAdmitted() {
  await ensureValidated();
  if (state.admitted) return;
  setStage('Build Admission', 'active'); setExecution('admission', 'Build Admission');
  addMsg({ sender: 'Host', label: 'admission · SIMULATED', tone: 'host', body: 'Admission granted. Authorization is default-deny: the host derived the allowed tool IDs from the 4 admitted actions in the frozen spec. Sandbox profile: pinned-default.' });
  addArtifact('admission_receipt.json', 'artifact', 1);
  addEvent('build_admitted', 'Host admitted 4 actions; tools: sandbox.exec, fs.patch, registry.pin.');
  state.admitted = true;
  setStage('Build Admission', 'done'); setExecution('admitted', 'Build');
  const run = $('#runBtn');
  run.disabled = false; run.textContent = 'Run Build';
  $('#runHelp').textContent = 'Admitted by the host. The Builder executes admitted operations only.';
  $('#nextAction').textContent = 'Build admitted by the host. Run the build to execute the 4 admitted TODOs.';
}
async function runBuildTodos(ids, prefix) {
  setStage('Build', 'active');
  for (const id of ids) {
    setTodo(id, 'doing');
    addEvent('tool_execution', prefix + id + ' executing in pinned sandbox (digest rechecked by host).');
    await sleep(700);
    setTodo(id, 'done');
  }
}
async function ensureBuilt() {
  await ensureAdmitted();
  if (state.stageState['Build'] === 'done') return;
  setProgress(12, 'Build progress');
  await runBuildTodos(TODO_DEFS.map((t) => t.id), '');
  setProgress(100, 'Build complete');
  addArtifact('build_result.json', 'artifact', 1);
  addEvent('build_completed', 'Builder finished 4/4 admitted actions; build_result.json persisted.');
  addMsg({ sender: 'Builder', label: 'SIMULATED', body: 'Build complete — 4/4 admitted actions executed. I executed admitted operations only; no scope expansion.' });
  setStage('Build', 'done'); setExecution('build_completed', 'Verification');
  $('#nextAction').textContent = 'Build completed 4/4 admitted actions. Next: independent verification.';
}
async function ensureVerified() {
  await ensureBuilt();
  if (state.stageState['Verification'] === 'done') return;
  setStage('Verification', 'active'); setExecution('verifying', 'Verification');
  addMsg({ sender: 'Build Verifier', label: 'independent E2E · SIMULATED', tone: 'host', body: 'Independent verification passed 6/6 acceptance criteria. I verified against the frozen criteria — I do not self-certify the build.' });
  addArtifact('verification_report.json', 'artifact', 1);
  addEvent('verification_passed', 'Independent verifier: 6/6 criteria passed.');
  setStage('Verification', 'done'); setExecution('completed_verified', 'Complete');
  $('#nextAction').textContent = 'Verified 6/6 criteria. Open task_summary.json for the final overview.';
}
async function ensureComplete() {
  await ensureVerified();
  if (!state.artifacts.find((a) => a.name === 'task_summary.json')) {
    addArtifact('task_summary.json', 'artifact', 1);
    addEvent('task_completed', 'Workflow completed and verified; final snapshot persisted.');
  }
}

/* ---------- action implementations (op -> visible behavior) ---------- */
function submitCurrent() {
  const text = $('#promptInput').value.trim();
  const purpose = $('#purposeSelect').value;
  if (!text) return;
  $('#promptInput').value = '';
  $('#sendBtn').disabled = true;
  addMsg({ side: 'user', body: text });
  ensureTask(text, purpose);
  addMsg({ sender: 'Host', label: 'SIMULATED', tone: 'host', body: `Task ${TASK_ID.slice(0, 8)}… created. The host froze your input as task_input.md rev 1.\nNext: run ${titleize(purpose)} when ready.` });
}
const OPS = {
  assertVisible: async (a) => {
    const el = $(a.target);
    if (el && a.args?.text && !el.textContent.includes(a.args.text)) toast('Note: expected text not present yet — ' + a.args.text, 'warn');
    el?.scrollIntoView({ block: 'nearest' });
  },
  fillComposer: async (a) => { const i = $('#promptInput'); i.value = a.args.text; i.dispatchEvent(new Event('input', { bubbles: true })); $('#sendBtn').disabled = !i.value.trim(); },
  setPurpose: async (a) => { $('#purposeSelect').value = a.args.value; state.capability = titleize(a.args.value); $('#statCapability').textContent = state.capability; },
  submit: async () => { submitCurrent(); },
  hostAccept: async () => { addEvent('input_frozen', 'Host accepted the request and froze task_input.md rev 1.'); toast('Host accepted the request — input frozen at rev 1'); },
  runStage: async () => { $('#runBtn')?.click(); },
  streamResearch: async () => { ensureTask('Research the OneShot repository: map the agent package, providers, and host gates', 'research'); await ensureResearch(false); },
  evidenceEvent: async () => { $('#eventList').scrollIntoView({ block: 'nearest' }); },
  openArtifact: async (a) => { openArtifact(a.args.name); },
  closeModal: async () => { closeArtifact(); if (!$('#settingsModal').hidden) $('#settingsModal').hidden = true; },
  switchToAudit: async (a) => { await ensureResearch(true); const i = $('#promptInput'); i.value = a.args.text; $('#sendBtn').disabled = false; $('#purposeSelect').value = 'audit'; state.capability = 'Audit'; },
  submitFollowup: async () => { const text = $('#promptInput').value.trim() || 'Now audit the agent package read-only and record CodeIntent candidates'; $('#promptInput').value = ''; $('#sendBtn').disabled = true; addMsg({ side: 'user', body: text }); },
  runAudit: async () => { await ensureAudit(); },
  stageDone: async () => {},
  planStart: async () => { await ensurePlan(); },
  todosAppear: async () => { renderTodos(); $('#todoBlock').scrollIntoView({ block: 'nearest' }); },
  todoProgress: async () => { setTodo('TODO-1', 'doing'); await sleep(600); setTodo('TODO-1', 'done'); setTodo('TODO-2', 'doing'); await sleep(600); setTodo('TODO-2', 'done'); addEvent('plan_progress', 'Planning TODOs drafted for TODO-1 and TODO-2.'); },
  planFreezeMsg: async () => { addMsg({ sender: 'Host', label: 'freeze · SIMULATED', tone: 'host', body: 'Freeze confirmed. build_spec.json rev 1 is immutable; any correction requires a new revision.' }); },
  validateStart: async () => { await ensurePlan(); setStage('Fixture Validation', 'active'); addMsg({ sender: 'Fixture Validator', label: 'independent · SIMULATED', tone: 'host', body: 'Validating the frozen BuildSpec: producer/consumer closure, stage effect gates, and per-stage concern ownership…' }); addEvent('validation_started', 'Fixture Validator opened build_spec.json rev 1.'); },
  validateReject: async () => {
    setStage('Fixture Validation', 'blocked'); setTodo('TODO-3', 'failed');
    showAlert('Fixture validation rejected: TODO-3 tool digest is missing from the ToolRegistrySnapshot. Missing provenance is a blocker.');
    addArtifact('fixture_report.json', 'artifact', 1);
    addMsg({ sender: 'Fixture Validator', label: 'REJECTED · SIMULATED', tone: 'warn', body: 'REJECTED — TODO-3 (registry.pin) has no pinned digest in the ToolRegistrySnapshot.\nMissing provenance is a blocker, not an implicit external dependency. The spec must be corrected and re-frozen.' });
    addEvent('validation_rejected', 'Rejected: TODO-3 digest provenance missing.');
  },
  correctSpec: async () => {
    await streamMsg({ sender: 'Planner', label: 'correction · SIMULATED' }, 'Correcting the spec: I pinned digest sha256:9f2c…e41a for registry.pin from the host ToolRegistrySnapshot. Requesting a host re-freeze.');
    addArtifact('build_spec.json', 'artifact', 2);
    addMsg({ sender: 'Host', label: 're-freeze · SIMULATED', tone: 'host', body: 'Correction accepted. build_spec.json rev 2 is frozen with the pinned digest. TODO-3 is unblocked.' });
    hideAlert(); setTodo('TODO-3', 'pending');
    addEvent('spec_corrected', 'build_spec.json rev 2 frozen (digest sha256:9f2c…e41a).');
  },
  revalidate: async () => {
    addMsg({ sender: 'Fixture Validator', label: 'independent · SIMULATED', tone: 'host', body: 'Re-validation passed against rev 2. All provenance, closure, and gate checks are green.' });
    addArtifact('fixture_report.json', 'artifact', 2);
    setStage('Fixture Validation', 'done'); setExecution('validated', 'Build Admission');
    addEvent('validation_passed', 'Fixture Validator passed build_spec.json rev 2.');
  },
admissionStart: async () => { await ensureValidated(); setStage('Build Admission', 'active'); addMsg({ sender: 'Host', label: 'admission · SIMULATED', tone: 'host', body: 'Evaluating Build Admission gates: host authorization, pinned tool digests, sandbox profile, stage effect gates. Default is deny.' }); addEvent('admission_check', 'Host evaluating admission gates (default-deny).'); },
  admissionDeny: async () => {
    addMsg({ sender: 'Builder', label: 'denied · SIMULATED', tone: 'warn', body: 'Direct execution attempt denied. A Builder request with an arbitrary tool string does not grant execution — only host-admitted actions may run.' });
    showAlert('Admission gate: direct Builder execution denied (default-deny). Only host-admitted actions may run.');
    addEvent('admission_denied', 'Direct Builder execution denied by host gate.');
    await sleep(900); hideAlert();
  },
  admissionGrant: async () => { await ensureAdmitted(); },
  buildStart: async () => {
    await ensureAdmitted();
    setExecution('running', 'Build'); setProgress(0, 'Build progress — executing admitted TODOs');
    addMsg({ sender: 'Builder', label: 'SIMULATED', body: '', bot: '<span class="typing"><i></i><i></i><i></i></span>' });
    transcript().lastElementChild?.querySelector('.typing')?.remove();
    addMsg({ sender: 'Builder', label: 'SIMULATED', body: 'Build started. Executing the 4 host-admitted TODOs in the pinned sandbox. The host rechecks tool identity, digest, and admission before every execution.' });
    addEvent('build_started', 'Builder started 4 admitted actions.');
  },
  buildTodo1: async () => { setTodo('TODO-1', 'doing'); addEvent('tool_execution', 'TODO-1 sandbox.exec — host rechecked identity + digest sha256:7be1…c204.'); await sleep(800); setTodo('TODO-1', 'done'); setProgress(25, 'Build progress — TODO-1 done'); },
  buildTodo2: async () => { setTodo('TODO-2', 'doing'); addEvent('tool_execution', 'TODO-2 fs.patch — secret redaction applied to error events.'); await sleep(800); setTodo('TODO-2', 'done'); setProgress(50, 'Build progress — TODO-2 done'); },
  buildTodo3: async () => { setTodo('TODO-3', 'doing'); addEvent('tool_execution', 'TODO-3 registry.pin — digest sha256:9f2c…e41a verified against snapshot.'); await sleep(800); setTodo('TODO-3', 'done'); setProgress(75, 'Build progress — TODO-3 done'); },
  buildTodo4: async () => { setTodo('TODO-4', 'doing'); addEvent('tool_execution', 'TODO-4 fs.patch — gate detail + completed_at ordering preserved.'); await sleep(800); setTodo('TODO-4', 'done'); setProgress(92, 'Build progress — TODO-4 done'); },
  buildArtifacts: async () => {
    setProgress(100, 'Build complete'); addArtifact('build_result.json', 'artifact', 1);
    addMsg({ sender: 'Builder', label: 'SIMULATED', body: 'Build complete — 4/4 admitted actions succeeded. build_result.json persisted with tool receipts.' });
    setStage('Build', 'done'); setExecution('build_completed', 'Verification');
    addEvent('build_completed', '4/4 actions succeeded; build_result.json rev 1.');
  },
  openSettings: async () => {
    ensureTask('Research the OneShot repository: map the agent package, providers, and host gates', 'research');
    setConnectorMessage('');
    $('#settingsModal').hidden = false;
  },
  fillEndpoint: async (a) => {
    $('#mcpUrl').value = a.args.value;
    $('#mcpAuthType').value = 'none';
    syncMcpAuthField();
  },
  testFail: async () => {
    await sleep(700);
    const detail = 'MCP server is unreachable';
    setMcpStatus('disconnected', detail);
    setConnectorMessage('MCP test failed: ' + detail);
    addEvent('mcp_error', 'MCP test failed: server unreachable at the invalid endpoint.');
    toast('MCP test failed — server unreachable', 'bad');
  },
  fixEndpoint: async (a) => {
    $('#mcpUrl').value = a.args.value;
    $('#mcpAuthType').value = 'none';
    syncMcpAuthField();
    setMcpStatus('disconnected');
    setConnectorMessage('Endpoint corrected. Run Test Connection again.');
  },
  testOk: async () => {
    await sleep(700);
    setMcpStatus('connected');
    setConnectorMessage('MCP test passed: 2 tools discovered');
    $('#mcpToken').value = '';
    addEvent('mcp_test_passed', 'MCP test discovered oneshot_research and source_lookup.');
  },
  connectMcp: async () => {
    await sleep(500);
    setMcpStatus('connected');
    setConnectorMessage('MCP connected: 2 tools discovered');
    $('#mcpToken').value = '';
    addEvent('mcp_connected', 'MCP connected over HTTP; two tools discovered.');
  },
  configureModel: async (a) => {
    $('#modelBaseUrl').value = a.args.baseUrl;
    $('#modelId').value = a.args.modelId;
    if (a.args.secretAction === 'capture-visible-dots') {
      $('#modelKey').value = '••••••••••••';
    }
    setModelStatus('disconnected');
  },
  testModel: async () => {
    await sleep(600);
    setModelStatus('connected', '', 'provider-ready');
    setConnectorMessage('Model test passed: provider-ready');
    $('#modelKey').value = '';
    addEvent('model_test_passed', 'Model test passed: provider-ready.');
  },
  saveModel: async () => {
    await sleep(350);
    const baseUrl = $('#modelBaseUrl').value.trim();
    const modelId = $('#modelId').value.trim();
    $('#savedModelId').textContent = modelId || 'No model selected';
    $('#savedModelUrl').textContent = baseUrl || 'No base URL configured';
    setModelStatus('saved', '', 'provider-ready');
    setConnectorMessage('Model settings saved');
    $('#modelKey').value = '';
    addMsg({ sender: 'Host', label: 'settings · SIMULATED', tone: 'host', body: 'Connection settings saved for this demo session. Only non-sensitive values remain in the UI; secret fields were cleared and were never recorded in the capture manifest.' });
    addEvent('model_settings_saved', 'Model settings saved; secret API key cleared.');
    toast('Model settings saved — secret cleared');
  },
interruptStart: async () => {
    await ensureAdmitted();
    setExecution('running', 'Build'); setStage('Build', 'active'); setProgress(0, 'Build progress — attempt 2');
    addMsg({ sender: 'Builder', label: 'SIMULATED', body: 'Build attempt 2 running from the admitted spec.' });
    setTodo('TODO-1', 'done'); setTodo('TODO-2', 'done'); setTodo('TODO-3', 'doing');
    setProgress(50, 'Build progress — TODO-3 executing');
    addEvent('build_started', 'Attempt 2: TODO-1 and TODO-2 complete; TODO-3 executing.');
  },
  interruptFail: async () => {
    setTodo('TODO-3', 'failed'); setProgress(50, 'Build interrupted at TODO-3', true);
    setStage('Build', 'failed'); setExecution('interrupted', 'Build');
    showAlert('Build interrupted: the sandbox worker disconnected during TODO-3. Completed TODOs are checkpointed; no partial effects were applied.');
    addMsg({ sender: 'Host', label: 'interruption · SIMULATED', tone: 'warn', body: 'The sandbox worker disconnected mid-TODO-3.\nExecution is interrupted. TODO-1 and TODO-2 are checkpointed; TODO-3 applied no partial effects.' });
    addEvent('build_interrupted', 'Sandbox worker disconnected during TODO-3.');
    toast('Build interrupted — checkpoint saved', 'bad');
  },
  recoverMsg: async () => {
    await streamMsg({ sender: 'Host', label: 'recovery · SIMULATED', tone: 'host' }, 'Recovery state is consistent. The checkpoint covers TODO-1 and TODO-2; admission is still valid for the frozen rev 2 spec. Resuming re-verifies the checkpoint before TODO-3 runs again.');
    addEvent('recovery_ready', 'Checkpoint verified: TODO-1/2 durable, TODO-3 safe to resume.');
  },
  resumeBuild: async () => { $('#runBtn').textContent = 'Resume Build'; toast('Resume requested — host re-verifying admission + checkpoint'); addEvent('resume_requested', 'Operator requested resume.'); },
  resumeProgress: async () => {
    hideAlert(); setStage('Build', 'active');
    setTodo('TODO-3', 'doing'); addEvent('tool_execution', 'TODO-3 resumed after checkpoint re-verification.'); await sleep(800);
    setTodo('TODO-3', 'done'); setProgress(75, 'Build progress — TODO-3 recovered');
    setTodo('TODO-4', 'doing'); await sleep(700); setTodo('TODO-4', 'done');
    setProgress(100, 'Build complete — recovered');
    addArtifact('build_result.json', 'artifact', 1);
    addMsg({ sender: 'Builder', label: 'recovered · SIMULATED', body: 'Resume complete. TODO-3 and TODO-4 finished; the build recovered with no duplicated effects.' });
    setStage('Build', 'done'); setExecution('build_completed', 'Verification');
    addEvent('build_completed', 'Recovered build finished 4/4 actions.');
  },
  verifyStart: async () => { await ensureBuilt(); setStage('Verification', 'active'); setExecution('verifying', 'Verification'); addMsg({ sender: 'Build Verifier', label: 'independent E2E · SIMULATED', tone: 'host', body: 'Starting independent verification. I run real end-to-end checks against the frozen acceptance criteria — I do not certify my own build.' }); addEvent('verification_started', 'Independent verifier opened the acceptance criteria.'); },
  verifyChecks: async () => {
    addMsg({ sender: 'Build Verifier', label: 'checks · SIMULATED', tone: 'host', body: 'Checks passing so far:', chips: ['✓ argv without shell', '✓ digest rechecked', '✓ secrets redacted'] });
    addEvent('verification_check', '3/6 criteria passing.');
  },
  verifyFailOne: async () => {
    addMsg({ sender: 'Build Verifier', label: 'flagged · SIMULATED', tone: 'warn', body: 'One criterion flagged: event ordering by sequence needs a fresh observation after the interruption. Requesting an ordered replay re-run before I sign off.' });
    showAlert('Verification: event-ordering criterion flagged — ordered replay re-run required.');
    addEvent('verification_flagged', 'Event ordering criterion flagged for re-run.');
    await sleep(900); hideAlert();
  },
  verifyRerun: async () => {
    await streamMsg({ sender: 'Build Verifier', label: 're-run · SIMULATED', tone: 'host' }, 'Ordered replay re-run passed: host events replay strictly by sequence with no gaps or duplicates. All 6 acceptance criteria are now green.');
    addArtifact('verification_report.json', 'artifact', 1);
    setStage('Verification', 'done'); setExecution('completed_verified', 'Complete');
    addEvent('verification_passed', 'Independent verifier: 6/6 criteria passed.');
  },
  finalSummary: async () => {
    await ensureComplete();
    addMsg({ sender: 'Host', label: 'complete · SIMULATED', tone: 'host', body: 'Workflow complete and independently verified.\nAll 8 stages are done and the final artifact snapshot is persisted for review.', chips: ['9 artifacts', '6/6 criteria', 'SIMULATED demo'] });
    addEvent('task_completed', 'Final overview ready: task_summary.json rev 1.');
    $('#nextAction').textContent = 'Workflow completed and verified. Open task_summary.json for the final overview.';
  },
  hoverArtifact: async () => { $('#artifactPanel').scrollIntoView({ block: 'nearest' }); },
};







/* ---------- playback engine ---------- */
function resetApp() {
  Object.assign(state, { task: null, events: [], artifacts: [], todos: [], seq: 0, stageState: {}, execution: 'idle', capability: 'Research', admitted: false, mcp: false, step: 0, playing: false });
  transcript().innerHTML = '';
  emptyState(); closeArtifact();
  $('#settingsModal').hidden = true;
  hideAlert(); $('#progressWrap').hidden = true;
  $('#progressFill').style.width = '0%'; $('#progressFill').classList.remove('failed');
  $('#topTaskTitle').textContent = 'No task loaded';
  $('#topTaskId').textContent = 'Create a task from System Chat';
  $('#summaryTitle').textContent = 'No task loaded';
  $('#nextAction').textContent = 'Submit a request in System Chat to create a host-backed task.';
  $('#statTaskId').textContent = '—';
  $('#statStage').textContent = '—';
  $('#statCapability').textContent = 'Research';
  setExecution('idle');
  const run = $('#runBtn');
  run.disabled = true; run.textContent = 'Create a task first';
  $('#runHelp').textContent = 'No task to execute yet.';
  const input = $('#promptInput'); input.value = '';
  $('#purposeSelect').value = 'research';
  $('#sendBtn').disabled = true;
  resetConnectors();
  $('#liveStatus').textContent = 'Auto-scroll is following the live transcript.';
  renderStages(); renderEvents(); renderArtifacts(); renderTodos();
  updateStepLabel();
}
function currentActions() { return state.scenario ? state.scenario.actions : []; }
function updateStepLabel() {
  const total = currentActions().length;
  $('#stepLabel').textContent = state.scenario
    ? `${state.scenario.id} · ${state.scenario.title} — step ${state.step}/${total}`
    : 'Ready — pick a scenario';
}
function revealCheckpoints(scenario, uptoStep) {
  for (const a of scenario.actions) {
    if (a.n > uptoStep && a.checkpoint && a.shot) {
      const el = document.createElement('meta');
      el.name = 'checkpoint';
      el.content = `${scenario.id}-${String(a.n).padStart(2, '0')}-${a.shot}`;
      document.head.appendChild(el);
    }
  }
}
async function runToStep(targetStep) {
  const scenario = state.scenario;
  if (!scenario) return;
  resetApp();
  revealCheckpoints(scenario, targetStep);
  for (const action of scenario.actions) {
    if (action.n > targetStep) break;
    const fn = OPS[action.op];
    if (!fn) throw new Error('Unknown op: ' + action.op);
    await fn(action);
    state.step = action.n;
    updateStepLabel();
  }
}
async function nextAction() {
  if (!state.scenario) { toast('Pick a scenario first', 'warn'); return; }
  if (state.step >= currentActions().length) { toast(state.scenario.id + ' finished — Reset or Play to replay', 'warn'); return; }
  await runToStep(state.step + 1);
}
async function prevAction() {
  if (!state.scenario || state.step === 0) return;
  await runToStep(state.step - 1);
}
async function waitWhilePaused() { while (state.paused) await sleep(200); }
async function playScenario() {
  if (!state.scenario || state.playing) return;
  state.playing = true; state.paused = false;
  await runToStep(0);
  for (const action of currentActions()) {
    if (!state.playing) break;
    await waitWhilePaused();
    await runToStep(action.n);
    await sleep(1100);
  }
  state.playing = false;
  toast(state.scenario.id + ' complete — ' + state.scenario.title);
}
async function playAll() {
  if (state.playing) return;
  state.playing = true; state.paused = false;
  for (const scenario of state.scenarios) {
    if (!state.playing) break;
    selectScenario(scenario.id, false);
    await runToStep(0);
    for (const action of scenario.actions) {
      if (!state.playing) break;
      await waitWhilePaused();
      await runToStep(action.n);
      await sleep(1100);
    }
  }
  state.playing = false;
  toast('All 12 scenarios complete');
}
function selectScenario(id, reset = true) {
  state.scenario = state.scenarios.find((s) => s.id === id) || state.scenarios[0];
  $('#scenarioSelect').value = state.scenario.id;
  if (reset) { runToStep(0); } else { state.step = 0; updateStepLabel(); }
}
/*__PART5B__*/

/* ---------- wiring + init ---------- */
function setPausedLabel() {
  $('#btnPause').textContent = state.paused ? '▶ Resume' : (state.playing ? '⏸ Pause' : '⏸ Pause');
}
function initControls() {
  $('#btnNext').addEventListener('click', () => nextAction());
  $('#btnPrev').addEventListener('click', () => prevAction());
  $('#btnPlay').addEventListener('click', () => { playScenario(); });
  $('#btnPlayAll').addEventListener('click', () => { playAll(); });
  $('#btnPause').addEventListener('click', () => {
    if (state.playing) { state.paused = !state.paused; }
    else if (state.paused) { state.paused = false; }
    setPausedLabel();
  });
  $('#btnReset').addEventListener('click', () => { state.playing = false; state.paused = false; setPausedLabel(); if (state.scenario) runToStep(0); else resetApp(); });
  $('#scenarioSelect').addEventListener('change', (e) => { state.playing = false; selectScenario(e.target.value, true); });
  $('#alertClose').addEventListener('click', hideAlert);
  $('#modalClose').addEventListener('click', closeArtifact);
  $('#modalClose2').addEventListener('click', closeArtifact);
  $('#artifactModal').addEventListener('click', (e) => { if (e.target.id === 'artifactModal') closeArtifact(); });
  $('#settingsClose').addEventListener('click', () => { $('#settingsModal').hidden = true; });
  $('#btnSettings').addEventListener('click', () => { $('#settingsModal').hidden = false; });
  $('#navSettings').addEventListener('click', () => { $('#settingsModal').hidden = false; });
  $('#mcpAuthType').addEventListener('change', syncMcpAuthField);
  $('#btnTestMcp').addEventListener('click', async () => {
    const v = $('#mcpUrl').value.trim();
    if (!v) { setMcpStatus('disconnected', 'MCP server URL is required'); setConnectorMessage('MCP test failed: MCP server URL is required'); return; }
    if (v.includes('invalid') || v.includes('example')) await OPS.testFail({});
    else await OPS.testOk({});
  });
  $('#btnConnectMcp').addEventListener('click', async () => {
    const v = $('#mcpUrl').value.trim();
    if (!v) { setMcpStatus('disconnected', 'MCP server URL is required'); setConnectorMessage('MCP connect failed: MCP server URL is required'); return; }
    if (v.includes('invalid') || v.includes('example')) await OPS.testFail({});
    else await OPS.connectMcp({});
  });
  $('#btnDisconnectMcp').addEventListener('click', async () => {
    setMcpStatus('disconnected');
    $('#mcpToken').value = '';
    setConnectorMessage('MCP disconnected');
    addEvent('mcp_disconnected', 'MCP disconnected by operator.');
  });
  $('#btnTestModel').addEventListener('click', async () => {
    if (!$('#modelBaseUrl').value.trim() || !$('#modelId').value.trim()) {
      setModelStatus('disconnected', 'API base URL and model ID are required');
      setConnectorMessage('Model test failed: API base URL and model ID are required');
      return;
    }
    await OPS.testModel({});
  });
  $('#btnSaveModel').addEventListener('click', () => OPS.saveModel({}));
  $('#btnClearSecrets').addEventListener('click', () => {
    $('#mcpToken').value = '';
    $('#modelKey').value = '';
    setConnectorMessage('Secrets cleared from this form. Non-sensitive fields were not changed.');
  });
  $('#navTask').addEventListener('click', () => $('#summary').scrollIntoView({ behavior: 'smooth' }));
  $('#navFiles').addEventListener('click', () => $('#artifactPanel').scrollIntoView({ behavior: 'smooth' }));
  $('#btnRefresh').addEventListener('click', () => toast(state.task ? 'Task state refreshed from host snapshot (SIMULATED)' : 'No task to refresh', 'warn'));
  $('#runBtn').addEventListener('click', async () => {
    if (!state.task) return;
    const label = $('#runBtn').textContent;
    if (label.includes('Research')) { await ensureResearch(false); }
    else if (label.includes('Audit')) { await ensureAudit(); }
    else if (label.includes('Resume')) { await OPS.resumeProgress({}); }
    else if (label.includes('Build')) { await OPS.buildStart({}); await OPS.buildTodo1({}); await OPS.buildTodo2({}); await OPS.buildTodo3({}); await OPS.buildTodo4({}); await OPS.buildArtifacts({}); }
  });
  $('#promptInput').addEventListener('input', (e) => { $('#sendBtn').disabled = !e.target.value.trim(); });
  $('#promptInput').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#composerForm').requestSubmit(); } });
  $('#composerForm').addEventListener('submit', (e) => { e.preventDefault(); submitCurrent(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeArtifact(); $('#settingsModal').hidden = true; } });
}
async function init() {
  try {
    const res = await fetch('scenarios.json');
    const data = await res.json();
    state.scenarios = data.scenarios || [];
  } catch { state.scenarios = []; }
  const select = $('#scenarioSelect');
  select.innerHTML = state.scenarios.map((s) => `<option value="${esc(s.id)}">${esc(s.id)} — ${esc(s.title)}</option>`).join('');
  initControls();
  const params = new URLSearchParams(location.search);
  const urlScenario = params.get('scenario');
  const urlStep = Number(params.get('step') || 0);
  // Playwright hooks: deterministic state inspection + checkpoint discovery.
  window.__demo = { state, OPS, runToStep, resetApp, selectScenario, version: '1.0.0' };
  if (urlScenario && state.scenarios.some((s) => s.id === urlScenario)) {
    selectScenario(urlScenario, false);
    await runToStep(urlStep);
  } else if (state.scenarios.length) {
    selectScenario(state.scenarios[0].id, true);
  } else {
    resetApp(); toast('scenarios.json failed to load — serve over HTTP', 'bad');
  }
}
init();


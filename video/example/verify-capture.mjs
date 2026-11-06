/**
 * Independent verification of the capture outputs.
 * Checks: scenario/action minimums, screenshot count + PNG dimensions
 * (1920x1080), SHA-256 match vs capture_manifest.json, no duplicate frames,
 * recordings + traces exist and are non-trivial, no secret-like strings in
 * demo/manifest inputs, SIMULATED labeling present. Writes verification.json.
 * Never marks unexecuted work as passed.
 */
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const failures = []
const checks = []
const ok = (name, pass, detail) => { checks.push({ name, pass, detail }); if (!pass) failures.push(name + ': ' + detail) }

const data = JSON.parse(fs.readFileSync(path.join(here, 'scenarios.json'), 'utf8'))
ok('scenarios count is 12', data.scenarios.length === 12, String(data.scenarios.length))
const minActions = { S01: 4, S02: 5, S03: 6, S04: 6, S05: 6, S06: 6, S07: 5, S08: 8, S09: 6, S10: 7, S11: 6, S12: 5 }
for (const s of data.scenarios) ok(`${s.id} has >= ${minActions[s.id]} actions`, s.actions.length >= (minActions[s.id] || 1), `${s.actions.length} actions`)
const totalActions = data.scenarios.reduce((a, s) => a + s.actions.length, 0)
ok('total actions >= 60', totalActions >= 60, String(totalActions))

const manifestPath = path.join(here, 'capture_manifest.json')
const manifest = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')) : { items: [] }
const checkpointCount = data.scenarios.reduce((a, s) => a + s.actions.filter((x) => x.checkpoint && x.shot).length, 0)
ok('manifest has >= 30 screenshots', manifest.items.length >= 30, String(manifest.items.length))
ok('manifest has at least 40 screenshots', manifest.items.length >= 40, String(manifest.items.length))
ok('manifest has no more than 60 screenshots', manifest.items.length <= 60, String(manifest.items.length))
ok('manifest covers every declared checkpoint', manifest.items.length === checkpointCount, `${manifest.items.length}/${checkpointCount}`)
const expectedFiles = new Set()
for (const s of data.scenarios) {
  for (const a of s.actions.filter((x) => x.checkpoint && x.shot)) {
    const dir = 'scenario-' + s.id.slice(1)
    const name = `${s.id}-${String(a.n).padStart(2, '0')}-${String(a.shot).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}.png`
    expectedFiles.add(`screenshots/${dir}/${name}`)
  }
}
const manifestFiles = new Set(manifest.items.map((item) => item.file))
for (const file of expectedFiles) if (!manifestFiles.has(file) || !fs.existsSync(path.join(here, file))) failures.push('missing checkpoint capture ' + file)
for (const file of manifestFiles) if (!expectedFiles.has(file)) failures.push('unexpected manifest screenshot ' + file)
ok('manifest file set exactly matches scenarios.json checkpoints', failures.filter((f) => f.startsWith('missing checkpoint') || f.startsWith('unexpected manifest')).length === 0, `${manifestFiles.size}/${expectedFiles.size}`)

function pngSize(file) {
  const b = fs.readFileSync(file)
  if (b.length < 24 || b.toString('ascii', 1, 4) !== 'PNG') return null
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) }
}
let dimsOk = 0
let hashOk = 0
const seen = new Set()
let dupes = 0
for (const item of manifest.items) {
  const file = path.join(here, item.file)
  if (!fs.existsSync(file)) { failures.push('missing file ' + item.file); continue }
  const size = pngSize(file)
  if (size && size.width === 1920 && size.height === 1080) dimsOk += 1
  else failures.push('bad dimensions ' + item.file + ' ' + JSON.stringify(size))
  const hash = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
  if (hash === item.sha256) hashOk += 1
  else failures.push('sha256 mismatch ' + item.file)
  const contentHash = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
  if (seen.has(contentHash)) dupes += 1
  seen.add(contentHash)
}
ok('all screenshots are 1920x1080 PNG', dimsOk === manifest.items.length && dimsOk > 0, `${dimsOk}/${manifest.items.length}`)
ok('all SHA-256 match manifest', hashOk === manifest.items.length && hashOk > 0, `${hashOk}/${manifest.items.length}`)
ok('no duplicate screenshots', dupes === 0, `${dupes} duplicates`)

const refDir = path.join(here, 'screenshots', 'reference')
const refs = fs.existsSync(refDir) ? fs.readdirSync(refDir).filter((f) => f.endsWith('.png')) : []
ok('real-backend reference captures present', refs.length >= 1, refs.join(', '))

const recordings = fs.existsSync(path.join(here, 'recordings')) ? fs.readdirSync(path.join(here, 'recordings')).filter((f) => f.endsWith('.webm')) : []
ok('12 scenario recordings exist', recordings.length === 12, `${recordings.length} webm`)
for (const r of recordings) ok(`recording non-trivial ${r}`, fs.statSync(path.join(here, 'recordings', r)).size > 20_000, fs.statSync(path.join(here, 'recordings', r)).size + ' bytes')
const traces = fs.existsSync(path.join(here, 'traces')) ? fs.readdirSync(path.join(here, 'traces')).filter((f) => f.endsWith('.zip')) : []
ok('12 scenario traces exist', traces.length === 12, `${traces.length} zip`)
for (const t of traces) ok(`trace non-trivial ${t}`, fs.statSync(path.join(here, 'traces', t)).size > 5_000, fs.statSync(path.join(here, 'traces', t)).size + ' bytes')

const secretPattern = /(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[baprs]-[A-Za-z0-9-]+)/
const scanFiles = ['demo.js', 'scenarios.json', 'index.html', 'capture_manifest.json', 'storyboard.json'].filter((f) => fs.existsSync(path.join(here, f)))
let secretHits = 0
for (const f of scanFiles) { if (secretPattern.test(fs.readFileSync(path.join(here, f), 'utf8'))) { secretHits += 1; failures.push('secret-like string in ' + f) } }
ok('no secret-like strings in demo inputs/manifest', secretHits === 0, `${secretHits} hits`)
const demoJs = fs.readFileSync(path.join(here, 'demo.js'), 'utf8')
ok('SIMULATED labeling present in demo', demoJs.includes('SIMULATED') && fs.readFileSync(path.join(here, 'index.html'), 'utf8').includes('SIMULATED'), 'badge + labels')

const report = {
  generatedAt: new Date().toISOString(),
  currentSourceCommit: manifest.currentSourceCommit || process.env.SOURCE_COMMIT || 'see README.md',
  referenceSourceCommit: manifest.referenceSourceCommit || 'd10ae4dc6b4b539ca43586dbeaf86c894591e3f8',
  evidenceBoundary: 'verification.json validates the simulated browser demo and its real Chromium captures; it does not certify current-HEAD backend execution. Reference frames depict API-backed live.html at the reference commit only.',
  status: failures.length === 0 ? 'passed' : 'failed',
  summary: {
    scenarios: data.scenarios.length,
    totalActions,
    manifestScreenshots: manifest.items.length,
    dimensionOk: dimsOk,
    hashOk,
    duplicates: dupes,
    referenceCaptures: refs,
    recordings: recordings.length,
    traces: traces.length,
  },
  checks,
  failures,
  notChecked: ['Muse Image 1.0 artwork (not used — optional per spec)', 'Cosmos 3 motion (not used — optional per spec)'],
}
fs.writeFileSync(path.join(here, 'verification.json'), JSON.stringify(report, null, 2))
console.log(JSON.stringify(report.summary, null, 2))
console.log('status:', report.status)
if (failures.length) { console.log('FAILURES:\n' + failures.join('\n')); process.exit(1) }

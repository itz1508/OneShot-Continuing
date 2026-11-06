/**
 * Real Chromium capture of the OneShot interactive demo.
 *
 * For every scenario in scenarios.json this script:
 *   - opens the demo in Chromium at 1920x1080 with video + trace recording
 *   - advances one action at a time by clicking the demo's Next Action control;
 *     the engine deterministically rebuilds each visible state in the browser,
 *     never by switching between prepared screenshot images
 *   - performs real Playwright click/hover/waitFor/screenshot interactions
 *   - captures one full-page screenshot per declared checkpoint
 *   - copies the recorded .webm video and saves the trace zip per scenario
 *   - writes capture_manifest.json with SHA-256 per screenshot
 *
 * Classification: workflow content is SIMULATED (labeled in-page); the browser
 * execution, pixels, videos, and traces are REAL captures of that demo.
 * Real-backend reference captures live in screenshots/reference/.
 */
import { chromium } from '../../web/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const BASE = process.env.DEMO_BASE || 'http://127.0.0.1:8917'
const data = JSON.parse(fs.readFileSync(path.join(here, 'scenarios.json'), 'utf8'))

const shotsRoot = path.join(here, 'screenshots')
const recRoot = path.join(here, 'recordings')
const traceRoot = path.join(here, 'traces')
for (const d of [shotsRoot, recRoot, traceRoot]) fs.mkdirSync(d, { recursive: true })

const sha256 = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

const checkpointFile = (scenario, action) => {
  const dirName = 'scenario-' + scenario.id.slice(1)
  const name = `${scenario.id}-${String(action.n).padStart(2, '0')}-${slug(action.shot)}.png`
  return { dirName, name, relative: `screenshots/${dirName}/${name}`, absolute: path.join(shotsRoot, dirName, name) }
}
const manifestPath = path.join(here, 'capture_manifest.json')
const resumed = fs.existsSync(manifestPath)
const manifest = resumed ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')) : {
  browser: 'Chromium (Playwright)',
  viewport: { width: 1920, height: 1080 },
  demoUrl: BASE + '/index.html',
  classification: {
    screenshots: 'REAL browser captures of the interactive demo at declared checkpoints',
    workflowContent: data.meta.classification + ' — simulated fixtures rendered by demo.js; every page carries a SIMULATED badge',
    referenceCaptures: 'screenshots/reference/*.png are REAL captures of the live OneShot backend UI on http://127.0.0.1:8000; referenceSourceCommit records the commit those frames depict',
  },
  items: [],
}
manifest.referenceSourceCommit = 'd10ae4dc6b4b539ca43586dbeaf86c894591e3f8'
manifest.currentSourceCommit = '3d2f3190c89d83ac1e3516199eb884de2f19e0f6'
const saveManifest = () => {
  manifest.generatedAt = new Date().toISOString()
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2))
}
const upsertManifestItem = (item) => {
  const index = manifest.items.findIndex((entry) => entry.file === item.file)
  if (index >= 0) manifest.items[index] = item
  else manifest.items.push(item)
}
const expectedRelative = new Set()
for (const scenario of data.scenarios) {
  for (const action of scenario.actions.filter((a) => a.checkpoint && a.shot)) expectedRelative.add(checkpointFile(scenario, action).relative)
}
manifest.items = manifest.items.filter((item) => expectedRelative.has(item.file) && fs.existsSync(path.join(here, item.file)))
for (const scenario of data.scenarios) {
  for (const action of scenario.actions.filter((a) => a.checkpoint && a.shot)) {
    const info = checkpointFile(scenario, action)
    if (!manifest.items.some((item) => item.file === info.relative) && fs.existsSync(info.absolute)) {
      upsertManifestItem({
        scenario: scenario.id, action: action.n, op: action.op, expected: action.expected, file: info.relative,
        sha256: sha256(info.absolute), bytes: fs.statSync(info.absolute).size, width: 1920, height: 1080,
        url: `${BASE}/index.html?scenario=${scenario.id}&step=0 (advanced with Next Action to step ${action.n})`,
        timestamp: fs.statSync(info.absolute).mtime.toISOString(),
        classification: 'REAL browser screenshot of SIMULATED demo workflow',
        recovered: 'manifest entry rebuilt from an existing capture after the interrupted run',
      })
    }
  }
}
saveManifest()
let browser = null
const launchBrowser = async () => chromium.launch({ args: ['--disable-gpu', '--disable-gpu-sandbox', '--disable-dev-shm-usage', '--use-gl=swiftshader'] })
const isScenarioComplete = (scenario) => {
  const recording = path.join(recRoot, scenario.id + '-recording.webm')
  const trace = path.join(traceRoot, scenario.id + '-trace.zip')
  if (!fs.existsSync(recording) || fs.statSync(recording).size < 20_000) return false
  if (!fs.existsSync(trace) || fs.statSync(trace).size < 5_000) return false
  return scenario.actions.filter((a) => a.checkpoint && a.shot).every((action) => {
    const info = checkpointFile(scenario, action)
    return fs.existsSync(info.absolute) && manifest.items.some((item) => item.file === info.relative && item.sha256 === sha256(info.absolute))
  })
}

for (const scenario of data.scenarios) {
  if (isScenarioComplete(scenario)) {
    console.log(scenario.id, 'already complete — resuming after it')
    continue
  }
  let completed = false
  let lastError = null
  for (let attempt = 1; attempt <= 3 && !completed; attempt += 1) {
    const dir = path.join(shotsRoot, 'scenario-' + scenario.id.slice(1))
    fs.mkdirSync(dir, { recursive: true })
    const videoDir = path.join(here, '.video-tmp', scenario.id + '-attempt-' + attempt)
    fs.rmSync(videoDir, { recursive: true, force: true })
    fs.mkdirSync(videoDir, { recursive: true })
    let context = null
    let page = null
    let tracingStarted = false
    try {
      if (!browser || !browser.isConnected()) browser = await launchBrowser()
      context = await browser.newContext({
        viewport: { width: 1920, height: 1080 },
        recordVideo: { dir: videoDir, size: { width: 1920, height: 1080 } },
      })
      page = await context.newPage()
      await context.tracing.start({ screenshots: true, snapshots: true })
      tracingStarted = true

      await page.goto(`${BASE}/index.html?scenario=${scenario.id}&step=0`, { waitUntil: 'domcontentloaded' })
      await page.waitForFunction(() => window.__demo && window.__demo.state.step === 0, null, { timeout: 30_000 })
      await page.waitForTimeout(500)

      for (const action of scenario.actions) {
        // Artifact/settings dialogs intentionally cover the product UI. Close an
        // open dialog with its real close control before advancing playback.
        if (await page.locator('#artifactModal:not([hidden])').count()) {
          await page.locator('#modalClose').click()
          await page.waitForFunction(() => document.querySelector('#artifactModal')?.hidden === true, null, { timeout: 10_000 })
        }
        if (await page.locator('#settingsModal:not([hidden])').count()) {
          await page.locator('#settingsClose').click()
          await page.waitForFunction(() => document.querySelector('#settingsModal')?.hidden === true, null, { timeout: 10_000 })
        }
        await page.locator('#btnNext').click()
        await page.waitForFunction((n) => window.__demo && window.__demo.state.step === n, action.n, { timeout: 30_000 })
        await page.waitForTimeout(action.checkpoint && action.shot ? 650 : 250)
        if (action.interaction === 'hover' && action.target) await page.locator(action.target).first().hover()
        if (action.op === 'openArtifact') await page.waitForSelector('#artifactModal:not([hidden])', { timeout: 10_000 })
        if (action.op === 'openSettings') await page.waitForSelector('#settingsModal:not([hidden])', { timeout: 10_000 })
        if (action.op === 'saveModel') {
          await page.waitForFunction(() => document.querySelector('#connectorMessage')?.textContent.includes('Model settings saved'), null, { timeout: 10_000 })
        }
        if (action.checkpoint && action.shot) {
          const info = checkpointFile(scenario, action)
          await page.screenshot({ path: info.absolute })
          upsertManifestItem({
            scenario: scenario.id, action: action.n, op: action.op, expected: action.expected, file: info.relative,
            sha256: sha256(info.absolute), bytes: fs.statSync(info.absolute).size, width: 1920, height: 1080,
            url: page.url(), timestamp: new Date().toISOString(),
            classification: 'REAL browser screenshot of SIMULATED demo workflow',
          })
          saveManifest()
          console.log(scenario.id, 'step', action.n, '->', info.name)
        }
      }

      const traceFile = path.join(traceRoot, scenario.id + '-trace.zip')
      await context.tracing.stop({ path: traceFile })
      tracingStarted = false
      await page.close()
      await context.close()
      context = null
      const videos = fs.readdirSync(videoDir).filter((f) => f.endsWith('.webm'))
      if (!videos.length) throw new Error('Playwright did not produce a video for ' + scenario.id)
      const dest = path.join(recRoot, scenario.id + '-recording.webm')
      fs.copyFileSync(path.join(videoDir, videos[0]), dest)
      console.log(scenario.id, 'video ->', path.basename(dest), fs.statSync(dest).size, 'bytes; trace', fs.statSync(traceFile).size, 'bytes')
      completed = true
    } catch (error) {
      lastError = error
      console.error(`${scenario.id} attempt ${attempt} failed: ${error.message}`)
      try { if (context && tracingStarted) await context.tracing.stop() } catch {}
      try { if (page && !page.isClosed()) await page.close() } catch {}
      try { if (context) await context.close() } catch {}
      try { if (browser) await browser.close() } catch {}
      browser = null
      if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, 1500))
    } finally {
      fs.rmSync(videoDir, { recursive: true, force: true })
    }
  }
  if (!completed) {
    saveManifest()
    throw lastError || new Error('Capture failed for ' + scenario.id)
  }
}

if (browser) await browser.close()
manifest.items.sort((a, b) => a.file.localeCompare(b.file))
saveManifest()
console.log(`DONE: ${manifest.items.length} screenshots across ${data.scenarios.length} scenarios`)


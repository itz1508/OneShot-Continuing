/**
 * Reference capture: screenshots of the REAL OneShot UI (live backend on :8000)
 * used as the visual reference for the standalone interactive demo.
 * Run: node reference-capture.mjs
 */
import { chromium } from '../../web/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const out = path.join(here, 'screenshots', 'reference')
fs.mkdirSync(out, { recursive: true })

const BASE = process.env.ONESHOT_BASE || 'http://127.0.0.1:8000'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })

async function shot(name) {
  await page.waitForTimeout(600)
  await page.screenshot({ path: path.join(out, name), fullPage: false })
  console.log('captured', name)
}

// 1. Initial screen (System Chat, empty state)
await page.goto(BASE + '/live.html', { waitUntil: 'networkidle' })
await shot('original-01-live-initial.png')

// 2. Type a request (real interaction with real UI)
const box = page.locator('textarea, [contenteditable="true"]').first()
if (await box.count()) {
  await box.click()
  await box.fill('Audit the agent package for security issues')
  await shot('original-02-request-typed.png')
  // 3. Submit to the real backend
  await page.keyboard.press('Enter')
  await page.waitForTimeout(4000)
  await shot('original-03-after-submit.png')
}

await browser.close()
console.log('done ->', out)

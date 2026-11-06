import { chromium } from '../../web/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const b = await chromium.launch({ args: ['--disable-gpu', '--disable-gpu-sandbox', '--use-gl=swiftshader'] })
const page = await b.newPage({ viewport: { width: 1280, height: 900 } })
await page.goto('https://www.youtube.com/watch?v=5MxKXDzl-SI&hl=en', { waitUntil: 'domcontentloaded', timeout: 60000 })
await page.waitForTimeout(4000)
const data = await page.evaluate(() => {
  const r = window.ytInitialPlayerResponse || {}
  const sd = r.streamingData || {}
  const summarizeFormat = (f) => ({
    keys: Object.keys(f),
    itag: f.itag,
    mimeType: f.mimeType,
    url: f.url ? f.url.slice(0, 240) : null,
    signatureCipher: f.signatureCipher ? f.signatureCipher.slice(0, 240) : null,
    cipher: f.cipher ? String(f.cipher).slice(0, 240) : null,
  })
  return {
    playabilityStatus: r.playabilityStatus,
    videoDetails: r.videoDetails,
    microformat: r.microformat,
    storyboards: r.storyboards || null,
    streamingDataKeys: Object.keys(sd),
    formats: (sd.formats || []).map(summarizeFormat),
    adaptiveFormats: (sd.adaptiveFormats || []).map(summarizeFormat),
  }
})
fs.writeFileSync(path.join(here, 'player-full-summary.json'), JSON.stringify(data, null, 2))
console.log(JSON.stringify({
  storyboards: data.storyboards,
  formats: data.formats,
  adaptiveFormats: data.adaptiveFormats.map((f) => ({ itag: f.itag, mimeType: f.mimeType, keys: f.keys, hasUrl: !!f.url, hasSignatureCipher: !!f.signatureCipher })),
}, null, 2))
await b.close()

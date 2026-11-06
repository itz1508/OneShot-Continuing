import { chromium } from '../../web/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const config = {
  L2: { cols: 5, rows: 5, tileW: 144, tileH: 90, intervalSec: 2, sheets: 4, count: 91 },
  L3: { cols: 3, rows: 3, tileW: 288, tileH: 180, intervalSec: 2, sheets: 11, count: 91 },
}

const browser = await chromium.launch({ args: ['--disable-gpu', '--disable-gpu-sandbox', '--use-gl=swiftshader'] })
const page = await browser.newPage()

for (const [level, cfg] of Object.entries(config)) {
  const srcDir = path.join(here, 'storyboards', level)
  const outDir = path.join(here, 'storyboards', level + '-tiles')
  fs.mkdirSync(outDir, { recursive: true })
  let index = 0
  for (let sheet = 0; sheet < cfg.sheets && index < cfg.count; sheet++) {
    const file = path.join(srcDir, `sheet-${sheet}.jpg`)
    const bytes = fs.readFileSync(file)
    const isJpeg = bytes[0] === 0xff && bytes[1] === 0xd8
    const isWebp = bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WEBP'
    if (!isJpeg && !isWebp) throw new Error(`${file} is neither JPEG nor WebP (${bytes.length} bytes)`)
    const dataUrl = `data:image/${isJpeg ? 'jpeg' : 'webp'};base64,` + bytes.toString('base64')
    await page.setContent(`<canvas id="c"></canvas>`)
    const tiles = await page.evaluate(async ({ dataUrl, cfg }) => {
      const img = new Image()
      img.src = dataUrl
      await img.decode()
      const canvas = document.querySelector('#c')
      canvas.width = cfg.tileW
      canvas.height = cfg.tileH
      const ctx = canvas.getContext('2d')
      const out = []
      for (let row = 0; row < cfg.rows; row++) {
        for (let col = 0; col < cfg.cols; col++) {
          ctx.clearRect(0, 0, cfg.tileW, cfg.tileH)
          ctx.drawImage(img, col * cfg.tileW, row * cfg.tileH, cfg.tileW, cfg.tileH, 0, 0, cfg.tileW, cfg.tileH)
          out.push(canvas.toDataURL('image/png'))
        }
      }
      return { width: img.naturalWidth, height: img.naturalHeight, out }
    }, { dataUrl, cfg })
    console.log(level, 'sheet', sheet, 'image', tiles.width + 'x' + tiles.height)
    for (const data of tiles.out) {
      if (index >= cfg.count) break
      const t = index * cfg.intervalSec
      const name = `t${String(t).padStart(3, '0')}.png`
      fs.writeFileSync(path.join(outDir, name), Buffer.from(data.split(',')[1], 'base64'))
      index++
    }
  }
  console.log(level, 'wrote', index, 'tiles')
}
await browser.close()

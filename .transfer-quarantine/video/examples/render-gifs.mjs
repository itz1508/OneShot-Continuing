// Capture ten four-second product workflow storyboards with Playwright and Pillow.
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { once } from 'node:events';

const require = createRequire(import.meta.url);
const { chromium } = require('../../web/node_modules/playwright');
const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../..');
const source = pathToFileURL(join(here, 'product-workflow.html')).href;
const frames = 40;
const requestedStyle = process.argv[2] ? Number(process.argv[2]) : null;
if (requestedStyle !== null && (!Number.isInteger(requestedStyle) || requestedStyle < 1 || requestedStyle > 10)) {
  throw new Error('Style must be an integer from 1 to 10');
}

async function writeFrame(stream, bytes) {
  const header = Buffer.allocUnsafe(4);
  header.writeUInt32BE(bytes.length);
  if (!stream.write(header)) await once(stream, 'drain');
  if (!stream.write(bytes)) await once(stream, 'drain');
}

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
  for (let style = requestedStyle ?? 1; style <= (requestedStyle ?? 10); style++) {
    const output = join(here, `workflow-style-${String(style).padStart(2, '0')}.gif`);
    const encoder = spawn('uv', ['run', '--no-sync', '--with', 'pillow', 'python', 'video/examples/encode-gif.py', output, String(frames)], {
      cwd: repo, stdio: ['pipe', 'inherit', 'inherit'], windowsHide: true,
    });
    for (let phase = 0; phase < frames; phase++) {
      await page.goto(`${source}?scene=${style}&frame=${phase}`);
      await page.locator('footer').waitFor();
      if (await page.locator('img').count()) {
        await page.locator('img').first().evaluate((img) => img.complete || img.decode());
      }
      await writeFrame(encoder.stdin, await page.screenshot());
    }
    encoder.stdin.end();
    const [code] = await once(encoder, 'close');
    if (code !== 0) throw new Error(`GIF encoder failed for style ${style}: ${code}`);
  }
} finally {
  await browser.close();
}

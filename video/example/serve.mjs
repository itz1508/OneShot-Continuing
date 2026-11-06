/**
 * Minimal static file server for the OneShot interactive demo.
 * Serves this directory on http://127.0.0.1:8917 (PORT env override).
 * Used by playwright.config.js webServer and for manual browsing.
 */
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(fileURLToPath(import.meta.url))
const port = Number(process.env.PORT || 8917)
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json',
  '.png': 'image/png',
  '.md': 'text/markdown; charset=utf-8',
}

const server = http.createServer((req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost')
    let file = path.join(root, decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname))
    if (!file.startsWith(root)) { res.writeHead(403); return res.end('forbidden') }
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end('not found') }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' })
    fs.createReadStream(file).pipe(res)
  } catch (e) {
    res.writeHead(500); res.end(String(e))
  }
})
server.listen(port, '127.0.0.1', () => console.log(`demo server http://127.0.0.1:${port}`))

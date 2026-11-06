// Playwright config for the OneShot interactive demo capture suite.
// Uses @playwright/test from ../../web/node_modules (no separate install).
// Run: node ../../web/node_modules/@playwright/test/cli.js test -c playwright.config.js
// (from this directory). The real multi-scenario capture is capture.mjs;
// capture.spec.js is an interactive smoke + step-through suite.
import { defineConfig } from '../../web/node_modules/@playwright/test/index.mjs'

export default defineConfig({
  testDir: '.',
  testMatch: 'capture.spec.js',
  timeout: 120_000,
  retries: 0,
  reporter: [['list']],
  outputDir: 'test-results',
  use: {
    baseURL: 'http://127.0.0.1:8917',
    viewport: { width: 1920, height: 1080 },
    trace: 'on',
    video: 'on',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'node serve.mjs',
    url: 'http://127.0.0.1:8917',
    reuseExistingServer: true,
    timeout: 30_000,
  },
})

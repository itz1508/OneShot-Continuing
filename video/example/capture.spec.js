/**
 * Playwright Test suite for the OneShot interactive demo.
 * classification: REAL browser interactions driving the SIMULATED demo workflow
 * (every in-page event is labeled SIMULATED; no real backend is called).
 *
 * Run (from this directory):
 *   node ../../web/node_modules/@playwright/test/cli.js test -c playwright.config.js
 * The deterministic multi-scenario screenshot/video/trace capture is capture.mjs.
 */
import { test, expect } from '../../web/node_modules/@playwright/test/index.mjs'

test.describe('OneShot interactive demo (SIMULATED workflow, real browser)', () => {
  test('loads with OneShot System Chat, SIMULATED badge, and scenario controls', async ({ page }) => {
    await page.goto('/index.html')
    await expect(page.locator('.sim-badge')).toHaveText('SIMULATED')
    await expect(page.locator('.eyebrow').first()).toHaveText('SYSTEM CHAT')
    await expect(page.locator('#transcript')).toContainText('What should OneShot look into?')
    await expect(page.locator('#scenarioSelect option')).toHaveCount(12)
    await page.screenshot({ path: 'screenshots/spec-01-demo-loaded.png' })
  })

  test('Next/Previous stepping drives visible state changes (S01)', async ({ page }) => {
    await page.goto('/index.html?scenario=S01&step=0')
    await expect(page.locator('#stepLabel')).toContainText('S01')
    await page.locator('#btnNext').click()
    await page.locator('#btnNext').click()
    await expect(page.locator('#promptInput')).toHaveValue(/Audit the agent package/)
    await page.locator('#btnNext').click()
    await page.locator('#btnNext').click()
    await expect(page.locator('#statTaskId')).toContainText('a3f9c1e8')
    await expect(page.locator('#transcript .msg.user')).toHaveCount(1)
    await page.locator('#btnPrev').click()
    await page.locator('#btnReset').click()
    await expect(page.locator('#transcript')).toContainText('What should OneShot look into?')
    await page.screenshot({ path: 'screenshots/spec-02-stepping.png' })
  })

  test('manual typing + submit creates a task through the composer', async ({ page }) => {
    await page.goto('/index.html?scenario=S01&step=0')
    await page.locator('#promptInput').fill('Audit the agent package for security issues and plan the fixes')
    await page.locator('#purposeSelect').selectOption('audit')
    await page.locator('#sendBtn').click()
    await expect(page.locator('#statExecution')).toHaveText('awaiting_mcp')
    await expect(page.locator('.artifact-row').first()).toContainText('task_input.md')
    await page.screenshot({ path: 'screenshots/spec-03-manual-submit.png' })
  })

  test('artifact modal opens and closes for research evidence (S03)', async ({ page }) => {
    await page.goto('/index.html?scenario=S03&step=6')
    await page.locator('.artifact-row').filter({ hasText: 'task_research.json' }).click()
    await expect(page.locator('#artifactModal')).toBeVisible()
    await expect(page.locator('#file-editor')).toHaveValue(/"task_id"/)
    await page.locator('#modalClose').click()
    await expect(page.locator('#artifactModal')).toBeHidden()
  })

  test('connection settings mirrors MCP and model connector flows (S09)', async ({ page }) => {
    await page.goto('/index.html?scenario=S09&step=0')
    await page.locator('#btnSettings').click()
    const dialog = page.getByRole('dialog', { name: 'Connection settings' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('MCP CONNECTION')).toBeVisible()
    await expect(dialog.getByText('MODEL API CONFIGURATION')).toBeVisible()

    await page.getByLabel('MCP server URL').fill('https://mcp.example.invalid/mcp')
    await page.getByLabel('Authentication type').selectOption('none')
    await page.getByRole('button', { name: 'Test Connection' }).first().click()
    await expect(page.getByText('MCP test failed: MCP server is unreachable')).toBeVisible()
    await expect(page.getByText('No tools discovered yet.')).toBeVisible()

    await page.getByLabel('MCP server URL').fill('http://127.0.0.1:9234/mcp')
    await page.getByRole('button', { name: 'Test Connection' }).first().click()
    await expect(page.getByText('MCP test passed: 2 tools discovered')).toBeVisible()
    await expect(page.getByText('oneshot_research', { exact: true })).toBeVisible()
    await expect(page.getByText('source_lookup', { exact: true })).toBeVisible()
    await page.locator('#btnConnectMcp').click()
    await expect(page.getByText('MCP connected: 2 tools discovered')).toBeVisible()
    await expect(page.locator('#mcpPill')).toContainText('MCP connected')

    await page.getByLabel('API base URL').fill('https://api.example.test/v1')
    await page.getByLabel('Model ID').fill('test-model')
    await expect(page.getByLabel('Secret API key')).toHaveValue('')
    await page.getByRole('button', { name: 'Test Connection' }).last().click()
    await expect(page.locator('#connectorMessage')).toHaveText('Model test passed: provider-ready')
    await expect(page.getByText('Provider response: provider-ready')).toBeVisible()
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.locator('#connectorMessage')).toHaveText('Model settings saved')
    await expect(page.getByText('test-model', { exact: true })).toBeVisible()
    await expect(page.getByLabel('Secret API key')).toHaveValue('')
    await page.screenshot({ path: 'screenshots/spec-04-connection-settings.png' })
  })
})

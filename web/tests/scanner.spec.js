import { test, expect } from '@playwright/test'

test('Scanner UI cannot dispatch without an active Planning task and host evidence', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Task request' }).fill('Inspect planning graph')
  await page.getByRole('button', { name: 'Submit task' }).click()

  await page.locator('.scanner-tool summary').click()
  await expect(page.getByText('Scanner requires the active Planning stage.')).toBeVisible()
  const execute = page.getByRole('button', { name: 'Run host Scanner' })
  await expect(execute).toBeDisabled()

  await page.getByRole('textbox', { name: 'Scanner request JSON' }).fill(
    JSON.stringify({
      run_id: 'invented',
      repository_identity: 'unverified',
      capabilities: ['dependency_readiness'],
    }),
  )
  await expect(execute).toBeDisabled()
  await page.reload()
  await page.locator('.scanner-tool summary').click()
  await expect(execute).toBeDisabled()
})

import { expect, test } from '@playwright/test';

test('phase-labs screener panel can render result rows', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('finsight-entry-mode', 'anonymous');
    localStorage.setItem('finsight-session-id', 'public:anonymous:e2e-phase-labs');
  });

  await page.route('**/api/screener/run', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        market: 'US',
        count: 1,
        items: [{ symbol: 'AAPL', name: 'Apple Inc.', price: 180.1, market_cap: 1000000000 }],
      }),
    });
  });

  await page.goto('/phase-labs');
  await page.getByRole('button', { name: '运行筛选' }).click();
  await expect(page.getByText('AAPL')).toBeVisible();
  await expect(page.getByText('Apple Inc.')).toBeVisible();
});

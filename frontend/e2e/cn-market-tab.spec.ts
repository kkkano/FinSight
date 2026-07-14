import { expect, test } from '@playwright/test';

test('CN market page loads fund-flow data', async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-entry-mode', 'anonymous');
    localStorage.setItem('finsight-session-id', 'public:anonymous:e2e-phase-labs');
  });

  await page.route('**/api/cn/market/fund-flow**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        count: 1,
        items: [{ symbol: '600519.SH', name: '贵州茅台', main_net_inflow: 1234567 }],
      }),
    });
  });

  await page.goto('/cn-market');
  await page.getByTestId('cn-market-load-btn').click();
  await expect(page.getByText('600519.SH')).toBeVisible();
  await expect(page.getByText('贵州茅台')).toBeVisible();
});

import { expect, test } from '@playwright/test';

test('phase-labs backtest panel renders metrics after run', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('finsight-entry-mode', 'anonymous');
    localStorage.setItem('finsight-session-id', 'public:anonymous:e2e-phase-labs');
  });

  await page.route('**/api/backtest/run', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        ticker: 'AAPL',
        strategy: 'ma_cross',
        metrics: {
          total_return_pct: 12.3,
          max_drawdown_pct: -4.2,
          trade_count: 9,
          win_rate_pct: 66.7,
        },
      }),
    });
  });

  await page.goto('/phase-labs');
  await page.getByRole('button', { name: '运行回测' }).click();
  await expect(page.getByText('总收益(%)')).toBeVisible();
  await expect(page.getByText('12.3')).toBeVisible();
});

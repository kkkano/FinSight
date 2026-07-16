import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-entry-mode', 'authenticated');
    localStorage.setItem('finsight-session-id', 'user:e2e-user:navigation');
  });
});

test.describe('移动导航', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('可展开、收起并进入 Dashboard', async ({ page }) => {
    await page.goto('/chat');
    const sidebar = page.getByTestId('sidebar');
    await expect(sidebar).toBeVisible();

    await page.getByRole('button', { name: '展开导航菜单' }).click();
    await expect(page.getByRole('button', { name: '收起导航菜单' })).toBeVisible();
    await page.getByTestId('sidebar-nav-dashboard').click();

    await expect(page).toHaveURL(/\/dashboard\/[A-Z0-9._-]+$/);
    await expect(page.getByRole('button', { name: '展开导航菜单' })).toBeVisible();
  });
});

test.describe('命令面板', () => {
  test('Ctrl+K 打开，Escape 关闭', async ({ page }) => {
    await page.goto('/chat');
    await page.keyboard.press('Control+k');

    const dialog = page.locator('div[role="dialog"][aria-label="命令面板"]');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('input[aria-label="搜索命令"]')).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
  });

  test('搜索结果支持键盘选择', async ({ page }) => {
    await page.goto('/dashboard/AAPL');
    const initialTheme = await page.evaluate(() => document.documentElement.classList.contains('dark'));
    await page.keyboard.press('Control+k');

    const dialog = page.locator('div[role="dialog"][aria-label="命令面板"]');
    const input = dialog.locator('input[aria-label="搜索命令"]');
    await input.fill('明暗主题');

    const options = dialog.locator('button[role="option"]');
    await expect(options.first()).toBeVisible();
    await expect(options.first()).toContainText('切换明暗主题');
    await input.press('Enter');
    await expect(dialog).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('dark')))
      .toBe(!initialTheme);
  });
});

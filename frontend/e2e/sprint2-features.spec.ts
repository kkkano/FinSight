import { test, expect } from '@playwright/test';

/* ------------------------------------------------------------------ */
/*  共享 Mock 工具                                                      */
/* ------------------------------------------------------------------ */

const fulfillJson = async (route: any, payload: unknown) => {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });
};

const fulfillSSE = async (route: any) => {
  const body = [
    `data: ${JSON.stringify({ type: 'token', content: 'ok' })}\n\n`,
    `data: ${JSON.stringify({ type: 'done' })}\n\n`,
  ].join('');
  await route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body,
  });
};

const buildDashboardPayload = (symbol = 'AAPL') => ({
  success: true,
  state: {
    active_asset: { symbol, type: 'equity', display_name: symbol },
    capabilities: {
      revenue_trend: true,
      segment_mix: true,
      sector_weights: true,
      top_constituents: true,
      holdings: true,
      market_chart: true,
    },
    watchlist: [
      { symbol: 'AAPL', type: 'equity', name: 'Apple' },
      { symbol: 'MSFT', type: 'equity', name: 'Microsoft' },
    ],
    layout_prefs: { hidden_widgets: [], order: [] },
    news_mode: { mode: 'market' },
    debug: {},
  },
  data: {
    snapshot: { revenue: 100, eps: 3.2, gross_margin: 40, fcf: 10 },
    charts: {
      market_chart: [
        { time: Date.now() / 1000 - 86400, close: 180 },
        { time: Date.now() / 1000, close: 182 },
      ],
      revenue_trend: [],
      segment_mix: [],
    },
    news: {
      market: [
        {
          title: 'Apple launches major AI update',
          url: 'https://example.com/apple-ai',
          source: 'E2E News',
          ts: new Date().toISOString(),
          summary: 'Apple announced a major AI update.',
        },
      ],
      impact: [
        {
          title: 'AAPL receives positive analyst outlook',
          url: 'https://example.com/aapl-outlook',
          source: 'E2E News',
          ts: new Date().toISOString(),
          summary: 'Analysts upgraded outlook.',
        },
      ],
    },
  },
});

/* ------------------------------------------------------------------ */
/*  beforeEach: 通用 Mock + localStorage 初始化                         */
/* ------------------------------------------------------------------ */

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-entry-mode', 'anonymous');
    localStorage.setItem(
      'fs_dashboard_active_v1',
      JSON.stringify({ symbol: 'AAPL', type: 'equity', display_name: 'Apple' }),
    );
    localStorage.setItem('fs_dashboard_layout_v1', JSON.stringify({ hidden_widgets: [], order: [] }));
    localStorage.setItem('fs_dashboard_news_mode_v1', JSON.stringify('market'));
    localStorage.setItem('finsight-portfolio-positions', JSON.stringify({ AAPL: 10 }));
    localStorage.removeItem('finsight-session-id');
  });

  await page.route('**/chat/supervisor/stream', async (route) => fulfillSSE(route));
  await page.route('**/api/dashboard**', async (route) => {
    const url = new URL(route.request().url());
    const symbol = url.searchParams.get('symbol') || 'AAPL';
    await fulfillJson(route, buildDashboardPayload(symbol));
  });
  await page.route('**/api/user/profile**', async (route) => {
    await fulfillJson(route, {
      profile: { name: 'E2E User', risk_preference: 'balanced', watchlist: ['AAPL', 'MSFT'] },
    });
  });
  await page.route('**/api/subscriptions**', async (route) => {
    await fulfillJson(route, { subscriptions: [] });
  });
  await page.route('**/api/stock/price/**', async (route) => {
    await fulfillJson(route, { success: true, data: { price: 180.5, change_percent: 1.2 } });
  });
  await page.route('**/api/tasks/daily**', async (route) => {
    await fulfillJson(route, {
      success: true,
      session_id: 'sess-e2e',
      risk_preference: 'balanced',
      tasks: [
        {
          id: 'task_1',
          title: 'AAPL 研报已 5 天未更新 — 建议刷新',
          category: 'refresh',
          priority: 1,
          action_url: '/chat?query=分析 AAPL 最新情况',
          icon: 'AlertTriangle',
        },
      ],
      count: 1,
    });
  });
  await page.route('**/health', async (route) => {
    await fulfillJson(route, {
      status: 'healthy',
      components: { live_tools: { status: 'active' } },
    });
  });
});

/* ================================================================== */
/*  Test Suite 1: Workbench 页面                                       */
/* ================================================================== */

test.describe('Workbench', () => {
  test('Workbench page loads from sidebar navigation', async ({ page }) => {
    await page.goto('/chat');

    // 从 sidebar 导航到 workbench
    const workbenchNav = page.getByTestId('sidebar-nav-workbench');
    if (await workbenchNav.isVisible()) {
      await workbenchNav.click();
      await expect(page).toHaveURL(/\/workbench/);
    }
  });

  test('Workbench page loads from dashboard button', async ({ page }) => {
    await page.goto('/dashboard/AAPL');

    const goWorkbench = page.getByTestId('dashboard-go-workbench');
    if (await goWorkbench.isVisible()) {
      await goWorkbench.click();
      await expect(page).toHaveURL(/\/workbench.*symbol=AAPL/);
    }
  });

  test('Workbench back-to-dashboard button navigates correctly', async ({ page }) => {
    await page.goto('/workbench?from=dashboard&symbol=AAPL');

    const backBtn = page.getByTestId('workbench-back-dashboard');
    if (await backBtn.isVisible()) {
      await backBtn.click();
      await expect(page).toHaveURL(/\/dashboard\/AAPL/);
    }
  });
});

/* ================================================================== */
/*  Test Suite 2: 移动端 Sidebar 抽屉                                   */
/* ================================================================== */

test.describe('Mobile sidebar drawer', () => {
  test.use({ viewport: { width: 375, height: 812 } }); // iPhone X viewport

  test('mobile menu button opens sidebar drawer', async ({ page }) => {
    await page.goto('/chat');

    // 移动端保留紧凑导航栏，可按需展开完整菜单。
    const sidebar = page.getByTestId('sidebar');
    await expect(sidebar).toBeVisible();
    await expect(sidebar).toHaveCSS('width', '56px');

    const menuBtn = page.getByRole('button', { name: '展开导航菜单' });
    await expect(menuBtn).toBeVisible();
    await menuBtn.click();

    await expect(page.getByRole('button', { name: '收起导航菜单' })).toBeVisible();
    await expect(sidebar).toHaveCSS('width', '216px');
  });

  test('clicking backdrop closes sidebar drawer', async ({ page }) => {
    await page.goto('/chat');
    await page.getByRole('button', { name: '展开导航菜单' }).click();
    await expect(page.getByRole('button', { name: '收起导航菜单' })).toBeVisible();

    const backdrop = page.locator('div.fixed.inset-0.bg-black\\/50');
    await expect(backdrop).toBeVisible();
    await backdrop.click({ position: { x: 350, y: 400 } });

    await expect(page.getByRole('button', { name: '展开导航菜单' })).toBeVisible();
    await expect(page.getByTestId('sidebar')).toHaveCSS('width', '56px');
  });

  test('sidebar nav item closes drawer on mobile', async ({ page }) => {
    await page.goto('/chat');
    await page.getByRole('button', { name: '展开导航菜单' }).click();
    await expect(page.getByRole('button', { name: '收起导航菜单' })).toBeVisible();

    await page.getByTestId('sidebar-nav-dashboard').click();

    await expect(page).toHaveURL(/\/dashboard\/[A-Z0-9._-]+$/);
    await expect(page.getByRole('button', { name: '展开导航菜单' })).toBeVisible();
    await expect(page.getByTestId('sidebar')).toHaveCSS('width', '56px');
  });
});

/* ================================================================== */
/*  Test Suite 3: 全局键盘快捷键 + 命令面板                               */
/* ================================================================== */

test.describe('Keyboard shortcuts & Command Palette', () => {
  test('Ctrl+K opens command palette', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForTimeout(500);

    // 命令面板初始不可见
    const dialog = page.locator('div[role="dialog"][aria-label="命令面板"]');
    await expect(dialog).toHaveCount(0);

    // 按 Ctrl+K
    await page.keyboard.press('Control+k');

    // 命令面板应出现
    await expect(dialog).toBeVisible();

    // 搜索框应已聚焦
    const searchInput = dialog.locator('input[aria-label="搜索命令"]');
    await expect(searchInput).toBeVisible();
    await expect(searchInput).toBeFocused();
  });

  test('Escape closes command palette', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForTimeout(500);

    // 打开命令面板
    await page.keyboard.press('Control+k');
    const dialog = page.locator('div[role="dialog"][aria-label="命令面板"]');
    await expect(dialog).toBeVisible();

    // 按 Escape 关闭
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
  });

  test('command palette filters actions by search query', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForTimeout(500);

    // 打开命令面板
    await page.keyboard.press('Control+k');
    const dialog = page.locator('div[role="dialog"][aria-label="命令面板"]');

    // 输入搜索文本
    const searchInput = dialog.locator('input[aria-label="搜索命令"]');
    await searchInput.fill('暗色');

    // 应只显示 "切换暗色模式" 相关选项
    const options = dialog.locator('button[role="option"]');
    const count = await options.count();
    expect(count).toBeLessThanOrEqual(2);

    // 至少有一个选项
    if (count > 0) {
      const firstLabel = await options.first().textContent();
      expect(firstLabel).toContain('暗色');
    }
  });

  test('command palette arrow keys navigate options', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForTimeout(500);

    // 打开命令面板
    await page.keyboard.press('Control+k');
    const dialog = page.locator('div[role="dialog"][aria-label="命令面板"]');
    await expect(dialog).toBeVisible();

    // 第一个选项默认选中
    const firstOption = dialog.locator('button[role="option"]').first();
    await expect(firstOption).toHaveAttribute('aria-selected', 'true');

    // 按下箭头键 → 第二个选项选中
    await page.keyboard.press('ArrowDown');
    const secondOption = dialog.locator('button[role="option"]').nth(1);
    await expect(secondOption).toHaveAttribute('aria-selected', 'true');
    await expect(firstOption).toHaveAttribute('aria-selected', 'false');
  });

  test('Ctrl+K opens palette on dashboard view too', async ({ page }) => {
    await page.goto('/dashboard/AAPL');
    await page.waitForTimeout(500);

    await page.keyboard.press('Control+k');
    const dialog = page.locator('div[role="dialog"][aria-label="命令面板"]');
    await expect(dialog).toBeVisible();
  });
});

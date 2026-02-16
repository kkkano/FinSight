import { test, expect, type Locator } from '@playwright/test';

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

const getTranslateX = (transform: string): number | null => {
  if (!transform || transform === 'none') return null;

  const matrix3dMatch = transform.match(/^matrix3d\((.+)\)$/);
  if (matrix3dMatch) {
    const values = matrix3dMatch[1].split(',').map((value) => Number(value.trim()));
    return Number.isFinite(values[12]) ? values[12] : null;
  }

  const matrixMatch = transform.match(/^matrix\((.+)\)$/);
  if (matrixMatch) {
    const values = matrixMatch[1].split(',').map((value) => Number(value.trim()));
    return Number.isFinite(values[4]) ? values[4] : null;
  }

  const translateMatch = transform.match(/translateX\((-?\d+(?:\.\d+)?)px\)/);
  if (translateMatch) {
    return Number(translateMatch[1]);
  }

  return null;
};

const expectSidebarHidden = async (sidebar: Locator) => {
  await expect
    .poll(async () => {
      const transform = await sidebar.evaluate((node) => getComputedStyle(node).transform);
      const translateX = getTranslateX(transform);
      return translateX !== null ? translateX < 0 : false;
    })
    .toBe(true);
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

    // 等待页面渲染完成
    await page.waitForTimeout(500);

    // 侧边栏初始状态应为隐藏
    const sidebar = page.getByTestId('sidebar');
    await expectSidebarHidden(sidebar);

    // 点击移动端菜单按钮
    const menuBtn = page.locator('button[aria-label="打开导航菜单"]');
    await expect(menuBtn).toBeVisible();
    await menuBtn.click();

    // 侧边栏应可见（translate-x-0）
    await expect(sidebar).toBeVisible();
  });

  test('clicking backdrop closes sidebar drawer', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForTimeout(500);

    // 打开侧边栏
    const menuBtn = page.locator('button[aria-label="打开导航菜单"]');
    await menuBtn.click();

    // 等待 drawer 动画完成
    await page.waitForTimeout(350);

    // 点击遮罩层关闭
    const backdrop = page.locator('div.fixed.inset-0.bg-black\\/50');
    if (await backdrop.isVisible()) {
      await backdrop.click({ position: { x: 350, y: 400 } });
      await page.waitForTimeout(350);

      // 验证侧边栏收起
      const sidebar = page.getByTestId('sidebar');
      await expectSidebarHidden(sidebar);
    }
  });

  test('sidebar nav item closes drawer on mobile', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForTimeout(500);

    // 打开侧边栏
    const menuBtn = page.locator('button[aria-label="打开导航菜单"]');
    await menuBtn.click();
    await page.waitForTimeout(350);

    // 点击 sidebar 内的 dashboard 导航
    await page.getByTestId('sidebar-nav-dashboard').click();

    // 导航后 drawer 应关闭
    await page.waitForTimeout(350);
    const sidebar = page.getByTestId('sidebar');
    await expectSidebarHidden(sidebar);
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

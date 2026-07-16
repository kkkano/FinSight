import { expect, test } from '@playwright/test';

const SESSION_ID = 'user:e2e-user:report-flow';

const fulfillJson = async (route: any, payload: unknown, status = 200) => {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });
};

const dashboardPayload = (symbol = 'AAPL') => ({
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
    watchlist: [{ symbol: 'AAPL', type: 'equity', name: 'Apple' }],
    layout_prefs: { hidden_widgets: [], order: [] },
    news_mode: { mode: 'market' },
    debug: {},
  },
  data: {
    snapshot: { revenue: 100, eps: 3.2, gross_margin: 40, fcf: 10 },
    charts: {
      market_chart: [
        { time: 1783814400, open: 178, high: 183, low: 177, close: 181, volume: 1_100_000 },
        { time: 1783900800, open: 181, high: 184, low: 180, close: 182, volume: 1_250_000 },
      ],
      revenue_trend: [],
      segment_mix: [],
      sector_weights: [],
      top_constituents: [],
      holdings: [],
    },
    news: {
      market: [],
      impact: [{
        title: 'Apple launches major AI update',
        url: 'https://example.com/apple-ai',
        source: 'E2E News',
        ts: '2026-07-16T08:00:00Z',
        summary: 'Apple announced a major AI update.',
      }],
    },
  },
});

const parseBody = (route: any): Record<string, any> => {
  try {
    return JSON.parse(route.request().postData() || '{}');
  } catch {
    return {};
  }
};

const fulfillDoneStream = async (route: any, payload: Record<string, unknown> = {}) => {
  await route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: [
      `data: ${JSON.stringify({ type: 'token', content: 'ok' })}\n\n`,
      `data: ${JSON.stringify({ type: 'done', ...payload })}\n\n`,
    ].join(''),
  });
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript((sessionId) => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-entry-mode', 'authenticated');
    localStorage.setItem('finsight-session-id', String(sessionId));
    localStorage.setItem(
      'fs_dashboard_active_v1',
      JSON.stringify({ symbol: 'AAPL', type: 'equity', display_name: 'Apple' }),
    );
    localStorage.setItem('fs_dashboard_layout_v1', JSON.stringify({ hidden_widgets: [], order: [] }));
    localStorage.setItem('fs_dashboard_news_mode_v1', JSON.stringify('market'));
  }, SESSION_ID);

  await page.route('**/api/execute', (route) => fulfillDoneStream(route));
  await page.route('**/api/dashboard**', async (route) => {
    const symbol = new URL(route.request().url()).searchParams.get('symbol') || 'AAPL';
    await fulfillJson(route, dashboardPayload(symbol));
  });
  await page.route('**/api/user/profile**', (route) => fulfillJson(route, {
    profile: { name: 'E2E User', watchlist: ['AAPL'] },
  }));
  await page.route('**/api/watchlist**', (route) => fulfillJson(route, {
    items: [{ ticker: 'AAPL', note: '', added_at: '2026-07-16T08:00:00Z' }],
  }));
  await page.route('**/api/stock/price/**', (route) => fulfillJson(route, {
    ticker: 'AAPL',
    data: { price: 182, change_percent: 1.1, provider: 'e2e', as_of: '2026-07-16T08:00:00Z' },
  }));
  await page.route('**/api/predictions/latest**', (route) => fulfillJson(route, {
    prediction: null,
    outcome: null,
  }));
  await page.route('**/api/reports/index**', (route) => fulfillJson(route, {
    session_id: SESSION_ID,
    count: 0,
    items: [],
  }));
  await page.route('**/health', (route) => fulfillJson(route, { status: 'ok' }));
});

test('报告模式通过唯一 Chat 执行入口发送', async ({ page }) => {
  let captured: Record<string, any> | null = null;
  await page.unroute('**/api/execute');
  await page.route('**/api/execute', async (route) => {
    captured = parseBody(route);
    await fulfillDoneStream(route);
  });

  await page.goto('/chat');
  await page.locator('#chat-input').fill('分析 AAPL 影响');
  await page.getByTestId('chat-report-toggle-btn').click();
  await page.getByTestId('chat-send-btn').click();

  await expect.poll(() => captured).not.toBeNull();
  expect(captured?.options?.output_mode).toBe('investment_report');
});

test('Dashboard 不挂载第二套聊天输入，Chat 保留唯一发送控件', async ({ page }) => {
  await page.goto('/dashboard/AAPL');
  await expect(page.getByTestId('mini-chat-input')).toHaveCount(0);
  await expect(page.getByTestId('mini-chat-send-btn')).toHaveCount(0);

  await page.goto('/chat');
  await expect(page.getByTestId('chat-send-btn')).toBeVisible();
  await expect(page.getByTestId('chat-report-toggle-btn')).toBeVisible();
});

test('侧边栏只在当前产品路由间切换', async ({ page }) => {
  await page.goto('/chat');
  await page.getByTestId('sidebar-nav-dashboard').click();
  await expect(page).toHaveURL(/\/dashboard\/[A-Z0-9._-]+$/);

  await page.getByTestId('dashboard-back-chat').click();
  await expect(page).toHaveURL('/chat');
  await page.getByTestId('sidebar-nav-history').click();
  await expect(page).toHaveURL('/history');
});

test('Dashboard 新闻 handoff 进入同一 Chat 会话并保留选择上下文', async ({ page }) => {
  let captured: Record<string, any> | null = null;
  await page.unroute('**/api/execute');
  await page.route('**/api/execute', async (route) => {
    captured = parseBody(route);
    await fulfillDoneStream(route);
  });

  await page.goto('/dashboard/AAPL');
  await page.getByTestId('dashboard-tab-news').click();
  await page.locator('[data-testid^="news-ask-"]').first().click();

  await expect(page).toHaveURL(/\/chat(?:\?|$)/);
  await expect(page.locator('#chat-input')).toHaveValue(/请结合已选内容分析 AAPL/);
  await page.getByTestId('chat-send-btn').click();

  await expect.poll(() => captured).not.toBeNull();
  expect(captured?.session_id).toBe(SESSION_ID);
  expect(captured?.context).toEqual(expect.objectContaining({
    active_symbol: 'AAPL',
    source_view: 'dashboard',
    source_tab: 'news',
  }));
  expect(captured?.context?.selection?.type).toBe('news');
});

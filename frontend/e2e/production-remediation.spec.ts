import { expect, test, type Page, type Route, type TestInfo } from '@playwright/test';

const SESSION_ID = 'public:anonymous:e2e-remediation';
const AS_OF = '2026-07-14';

const fulfillJson = async (route: Route, payload: unknown, status = 200) => {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });
};

const dashboardPayload = {
  success: true,
  state: {
    active_asset: { symbol: 'AAPL', type: 'equity', display_name: 'Apple' },
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
    snapshot: { price: 182, change: 2, change_percent: 1.11, revenue: 100, eps: 3.2 },
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
    technicals: {
      trend: 'neutral',
      support_levels: [178],
      resistance_levels: [185],
      moving_averages: {},
      oscillators: {},
    },
    indicator_series: {
      dates: [],
      rsi: [],
      macd: [],
      macd_signal: [],
      macd_histogram: [],
      bb_upper: [],
      bb_middle: [],
      bb_lower: [],
    },
    news: { market: [], impact: [] },
    meta: { market_chart: { as_of: AS_OF, source: 'e2e-fixture' } },
  },
};

const mockApi = async (route: Route) => {
  const url = new URL(route.request().url());
  const path = url.pathname;

  if (path === '/api/agents/predictions/latest') {
    await route.fulfill({ status: 204, body: '' });
    return;
  }
  if (path === '/api/dashboard/insights') {
    await fulfillJson(route, { success: true, symbol: 'AAPL', insights: {}, generated_at: `${AS_OF}T08:00:00Z` });
    return;
  }
  if (path === '/api/dashboard') {
    await fulfillJson(route, dashboardPayload);
    return;
  }
  if (path === '/api/user/profile') {
    await fulfillJson(route, { profile: { name: 'E2E User', risk_preference: 'balanced', watchlist: ['AAPL'] } });
    return;
  }
  if (path === '/api/subscriptions') {
    await fulfillJson(route, { subscriptions: [] });
    return;
  }
  if (path.startsWith('/api/stock/price/')) {
    await fulfillJson(route, { success: true, data: { price: 182, change_percent: 1.11 } });
    return;
  }
  if (path === '/api/tasks/daily') {
    await fulfillJson(route, {
      success: true,
      session_id: SESSION_ID,
      risk_preference: 'balanced',
      watchlist: ['AAPL'],
      tasks: [{
        id: 'task-e2e-1',
        title: '复核 AAPL 最新研究',
        category: 'refresh',
        priority: 1,
        action_url: '/chat?query=AAPL',
        icon: 'AlertTriangle',
      }],
      count: 1,
    });
    return;
  }
  if (path === '/api/portfolio/summary') {
    await fulfillJson(route, {
      success: true,
      session_id: SESSION_ID,
      positions: [{ ticker: 'AAPL', shares: 10, avg_cost: 170, live_price: 182, market_value: 1820, cost_basis: 1700 }],
      count: 1,
      priced_count: 1,
      total_value: 1820,
      total_cost: 1700,
      total_pnl: 120,
      total_day_change: 20,
    });
    return;
  }
  if (path === '/api/reports/index') {
    await fulfillJson(route, { success: true, session_id: SESSION_ID, count: 0, items: [] });
    return;
  }
  if (path === '/api/monitor/findings') {
    await fulfillJson(route, { findings: [], count: 0 });
    return;
  }
  if (path === '/api/monitor/targets') {
    await fulfillJson(route, { targets: [] });
    return;
  }
  if (path === '/api/monitor/settings') {
    await fulfillJson(route, { success: true, notify_email: null, notify_enabled: false, smtp_configured: false });
    return;
  }
  if (path === '/api/monitor/macro-calendar') {
    await fulfillJson(route, { success: true, events: [], as_of: `${AS_OF}T08:00:00Z` });
    return;
  }
  if (path.includes('/api/monitor/comments')) {
    await fulfillJson(route, { detail: 'monitor comments unavailable' }, 503);
    return;
  }
  if (path.startsWith('/api/conversations/')) {
    await fulfillJson(route, { success: true, messages: [] });
    return;
  }

  await fulfillJson(route, { success: true });
};

const preparePage = async (page: Page) => {
  await page.addInitScript((sessionId) => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-entry-mode', 'anonymous');
    localStorage.setItem('finsight-session-id', sessionId);
    localStorage.setItem(
      'fs_dashboard_active_v1',
      JSON.stringify({ symbol: 'AAPL', type: 'equity', display_name: 'Apple' }),
    );
    localStorage.setItem('fs_dashboard_layout_v1', JSON.stringify({ hidden_widgets: [], order: [] }));
    localStorage.setItem('fs_dashboard_news_mode_v1', JSON.stringify('market'));
  }, SESSION_ID);
  await page.route(/^https?:\/\/[^/]+\/api\//, mockApi);
  await page.route('**/health', async (route) => fulfillJson(route, { status: 'healthy' }));
};

const expectNoHorizontalOverflow = async (page: Page) => {
  await expect.poll(() => page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))).toEqual(expect.objectContaining({
    clientWidth: page.viewportSize()?.width,
    scrollWidth: page.viewportSize()?.width,
  }));
};

test.describe('WP6 production remediation paths', () => {
  test.beforeEach(async ({ page }) => preparePage(page));

  test('latest 204 keeps one primary K-line and dashboard handoff is editable before manual send', async ({ page }, testInfo) => {
    let streamCalls = 0;
    let sentPayload: Record<string, any> | null = null;
    await page.route('**/chat/supervisor/stream', async (route) => {
      streamCalls += 1;
      sentPayload = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `data: ${JSON.stringify({ type: 'done' })}\n\n`,
      });
    });

    const latestResponse = page.waitForResponse((response) => (
      response.url().includes('/api/agents/predictions/latest') && response.status() === 204
    ));
    await page.goto('/dashboard/AAPL?tab=technical');
    await latestResponse;

    const chart = page.getByTestId('dashboard-primary-candlestick');
    await expect(chart).toHaveCount(1);
    await expect(chart).toBeVisible();
    await expect(chart).toContainText('日线快照');
    await expect(chart).toContainText(AS_OF);
    await expect(chart.locator('svg, canvas')).toHaveCount(1);
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: testInfo.outputPath('dashboard-desktop.png'), fullPage: true });

    await page.getByTestId('dashboard-ask-ai').click();
    await expect(page).toHaveURL(/\/chat(?:\?|$)/);
    const composer = page.locator('#chat-input');
    await expect(composer).toBeFocused();
    await expect(composer).toHaveValue('关于 AAPL 的技术面，');
    expect(streamCalls).toBe(0);

    await page.getByTestId('chat-send-btn').click();
    await expect.poll(() => streamCalls).toBe(1);
    expect(sentPayload?.query).toBe('关于 AAPL 的技术面，');
    expect(sentPayload?.context).toEqual(expect.objectContaining({
      view: 'chat',
      active_symbol: 'AAPL',
      source_view: 'dashboard',
      source_tab: 'technical',
    }));
  });

  for (const viewport of [
    { name: 'desktop', width: 1440, height: 900 },
    { name: 'mobile', width: 390, height: 844 },
  ] as const) {
    test(`Workbench defaults to today and all four tabs remain reachable on ${viewport.name}`, async ({ page }, testInfo: TestInfo) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto('/workbench');

      await expect(page.getByTestId('workbench-tab-today')).toHaveAttribute('aria-selected', 'true');
      await expect(page.getByTestId('workbench-panel-today')).toBeVisible();
      await expect(page.getByTestId('workbench-today-queue')).toContainText('复核 AAPL 最新研究');
      const todayRows = page.getByTestId('workbench-today-queue').locator(':scope > div:nth-child(2) > div');
      expect(await todayRows.count()).toBeLessThanOrEqual(3);

      for (const tab of ['portfolio', 'research', 'monitor', 'today'] as const) {
        await page.getByTestId(`workbench-tab-${tab}`).click();
        await expect(page.getByTestId(`workbench-panel-${tab}`)).toBeVisible();
      }

      const tabsBox = await page.getByTestId('workbench-tabs').boundingBox();
      expect(tabsBox).not.toBeNull();
      expect(tabsBox!.x).toBeGreaterThanOrEqual(0);
      expect(tabsBox!.x + tabsBox!.width).toBeLessThanOrEqual(viewport.width);
      await expectNoHorizontalOverflow(page);
      await page.screenshot({ path: testInfo.outputPath(`workbench-${viewport.name}.png`), fullPage: true });
    });
  }
});

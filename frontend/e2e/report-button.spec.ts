import { test, expect } from '@playwright/test';

const E2E_SESSION_ID = 'sess-e2e-001';

const fulfillJson = async (route: any, payload: unknown) => {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });
};

const fulfillSSE = async (route: any, donePayload: Record<string, unknown> = {}) => {
  const body = [
    `data: ${JSON.stringify({ type: 'token', content: 'ok' })}\n\n`,
    `data: ${JSON.stringify({ type: 'done', ...donePayload })}\n\n`,
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
    active_asset: {
      symbol,
      type: 'equity',
      display_name: symbol,
    },
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
    snapshot: {
      revenue: 100,
      eps: 3.2,
      gross_margin: 40,
      fcf: 10,
    },
    charts: {
      market_chart: [
        { time: Date.now() / 1000 - 86400, close: 180 },
        { time: Date.now() / 1000, close: 182 },
      ],
      revenue_trend: [],
      segment_mix: [],
      sector_weights: [],
      top_constituents: [],
      holdings: [],
    },
    news: {
      market: [
        {
          title: 'Apple launches major AI update',
          url: 'https://example.com/apple-ai',
          source: 'E2E News',
          ts: new Date().toISOString(),
          summary: 'Apple announced a major AI update that may impact revenue growth.',
        },
      ],
      impact: [
        {
          title: 'AAPL receives positive analyst outlook',
          url: 'https://example.com/aapl-outlook',
          source: 'E2E News',
          ts: new Date().toISOString(),
          summary: 'Analysts upgraded long-term outlook after strong earnings guidance.',
        },
      ],
    },
  },
});

const parseRequestBody = (route: any) => {
  try {
    return JSON.parse(route.request().postData() || '{}');
  } catch {
    return {};
  }
};

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

  await page.route('**/chat/supervisor/stream', async (route) => {
    await fulfillSSE(route);
  });

  await page.route('**/api/dashboard**', async (route) => {
    const url = new URL(route.request().url());
    const symbol = url.searchParams.get('symbol') || 'AAPL';
    await fulfillJson(route, buildDashboardPayload(symbol));
  });

  await page.route('**/api/user/profile**', async (route) => {
    await fulfillJson(route, {
      profile: {
        name: 'E2E User',
        risk_preference: 'balanced',
        watchlist: ['AAPL', 'MSFT'],
      },
    });
  });

  await page.route('**/api/user/watchlist/add', async (route) => {
    await fulfillJson(route, { success: true });
  });

  await page.route('**/api/user/watchlist/remove', async (route) => {
    await fulfillJson(route, { success: true });
  });

  await page.route('**/api/subscriptions**', async (route) => {
    await fulfillJson(route, { subscriptions: [] });
  });

  await page.route('**/api/stock/price/**', async (route) => {
    await fulfillJson(route, { success: true, data: { price: 180.5, change_percent: 1.2 } });
  });

  await page.route('**/health', async (route) => {
    await fulfillJson(route, { status: 'ok' });
  });

});

test('ChatInput: deep mode + send uses options.output_mode=investment_report', async ({ page }) => {
  let captured: any = null;

  await page.route('**/chat/supervisor/stream', async (route) => {
    captured = parseRequestBody(route);
    await fulfillSSE(route);
  });

  await page.goto('/chat');

  await page.locator('#chat-input').fill('分析影响');
  await page.getByTestId('chat-mode-deep-btn').click();
  await page.getByTestId('chat-send-btn').click();

  await expect.poll(() => captured).not.toBeNull();
  expect(captured?.options?.output_mode).toBe('investment_report');
});

test('MiniChat: deep mode + send uses options.output_mode=investment_report', async ({ page }) => {
  let captured: any = null;

  await page.route('**/chat/supervisor/stream', async (route) => {
    captured = parseRequestBody(route);
    await fulfillSSE(route);
  });

  await page.goto('/dashboard/AAPL');

  await page.getByTestId('mini-chat-input').fill('分析影响');
  await page.getByTestId('mini-chat-mode-deep-btn').click();
  await page.getByTestId('mini-chat-send-btn').click();

  await expect.poll(() => captured).not.toBeNull();
  expect(captured?.options?.output_mode).toBe('investment_report');
});

test('Legacy /?symbol=AAPL route redirects to dashboard route', async ({ page }) => {
  await page.goto('/?symbol=AAPL');

  await expect(page).toHaveURL(/\/dashboard\/AAPL(?:\?symbol=AAPL)?$/);
  await expect(page.getByTestId('mini-chat-input')).toBeVisible();
});

test('Route switch: sidebar can switch between chat and dashboard', async ({ page }) => {
  await page.goto('/chat');

  await page.getByTestId('sidebar-nav-dashboard').click();
  await expect(page).toHaveURL(/\/dashboard\/[A-Z0-9._-]+$/);

  await page.getByTestId('dashboard-back-chat').click();
  await expect(page).toHaveURL('/chat');
});

test('Context panel tabs can switch and panel can collapse/expand', async ({ page }) => {
  await page.goto('/dashboard/AAPL');

  const panel = page.getByTestId('context-panel');
  await expect(panel).toBeVisible();

  await page.getByTestId('context-tab-chart').click();
  await expect(panel.getByText('Market Chart')).toBeVisible();

  await page.getByTestId('context-tab-portfolio').click();
  await expect(panel.getByText('Portfolio')).toBeVisible();

  await panel.locator('button[title="Collapse"]').click();
  await expect(page.getByTestId('context-panel-shell')).toHaveCount(0);

  const expandButton = page.getByTestId('context-panel-expand');
  await expect(expandButton).toBeVisible();
  await expandButton.click();

  await expect(page.getByTestId('context-panel-shell')).toBeVisible();
  await expect(page.getByTestId('context-panel')).toBeVisible();
});

test('Session continuity: chat and mini chat share session_id', async ({ page }) => {
  const payloads: any[] = [];

  await page.route('**/chat/supervisor/stream', async (route) => {
    const payload = parseRequestBody(route);
    payloads.push(payload);

    if (payloads.length === 1) {
      await fulfillSSE(route, { session_id: E2E_SESSION_ID });
      return;
    }

    await fulfillSSE(route);
  });

  await page.goto('/chat');

  await page.locator('#chat-input').fill('先来一条普通消息');
  await page.getByTestId('chat-send-btn').click();
  await expect.poll(() => payloads.length).toBeGreaterThanOrEqual(1);

  await page.getByTestId('sidebar-nav-dashboard').click();
  await expect(page).toHaveURL(/\/dashboard\/[A-Z0-9._-]+$/);

  await page.getByTestId('mini-chat-input').fill('再来一条消息');
  await page.getByTestId('mini-chat-send-btn').click();
  await expect.poll(() => payloads.length).toBeGreaterThanOrEqual(2);

  expect(typeof payloads[0]?.session_id).toBe('string');
  expect(payloads[1]?.session_id).toBe(E2E_SESSION_ID);
});

test('Selection reference: ask-from-news keeps selection context in request', async ({ page }) => {
  let captured: any = null;

  await page.route('**/chat/supervisor/stream', async (route) => {
    captured = parseRequestBody(route);
    await fulfillSSE(route);
  });

  await page.goto('/dashboard/AAPL');

  await page.getByText('新闻动态').scrollIntoViewIfNeeded();
  await expect(page.getByTitle('选择').first()).toBeVisible();
  await page.getByTitle('选择').first().click();

  await page.getByTestId('mini-chat-input').fill('基于这条新闻给个判断');
  await page.getByTestId('mini-chat-send-btn').click();

  await expect.poll(() => captured).not.toBeNull();
  expect(captured?.context?.active_symbol).toBe('AAPL');
  expect(captured?.context?.selection?.type).toBe('news');
  expect(captured?.context?.selection?.title).toContain('Apple launches major AI update');
});

import { expect, test } from '@playwright/test';

import { E2E_SESSION_ID, installAuthenticatedSession } from './helpers/auth';

const fulfillJson = async (route: any, payload: unknown) => {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });
};

// 研究活动保留在所属对话内，标的面板不重复提供执行页签。
const openResearchProcess = async (page: any) => {
  const summary = page.getByLabel('研究过程').getByRole('button').first();
  await expect(summary).toBeVisible();
  if (await summary.getAttribute('aria-expanded') !== 'true') await summary.click();
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
    watchlist: [{ symbol: 'AAPL', type: 'equity', name: 'Apple' }],
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
      sector_weights: [],
      top_constituents: [],
      holdings: [],
    },
    news: { market: [], impact: [] },
  },
});

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.fallback();
    if (path === '/api/conversations' && route.request().method() === 'POST') {
      return fulfillJson(route, { success: true, session_id: route.request().postDataJSON().session_id });
    }
    await fulfillJson(route, { success: true, items: [], messages: [], count: 0, profile: {} });
  });
  await page.addInitScript((sessionId) => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-session-id', sessionId);
    localStorage.setItem(
      'fs_dashboard_active_v1',
      JSON.stringify({ symbol: 'AAPL', type: 'equity', display_name: 'Apple' }),
    );
    localStorage.setItem('fs_dashboard_layout_v1', JSON.stringify({ hidden_widgets: [], order: [] }));
    localStorage.setItem('fs_dashboard_news_mode_v1', JSON.stringify('market'));
  }, E2E_SESSION_ID);
  await installAuthenticatedSession(page, { accessToken: 'fixture-token' });
  await page.route('**/api/models', (route) => fulfillJson(route, { models: [{ id: 'system:server-default', model: 'test-model',
    label: '验收模型', provider: 'system', available: true, native_tool_calls: true, effort_options: [] }], default_model_id: 'system:server-default' }));

  await page.route('**/api/dashboard**', async (route) => {
    const url = new URL(route.request().url());
    const symbol = url.searchParams.get('symbol') || 'AAPL';
    await fulfillJson(route, buildDashboardPayload(symbol));
  });
  await page.route('**/api/user/profile**', async (route) => {
    await fulfillJson(route, { profile: { name: 'E2E User', watchlist: ['AAPL'] } });
  });
  await page.route('**/api/stock/price/**', async (route) => {
    await fulfillJson(route, { success: true, data: { price: 180.5, change_percent: 1.2 } });
  });
  await page.route('**/api/reports/index**', async (route) => {
    await fulfillJson(route, { session_id: E2E_SESSION_ID, count: 0, items: [] });
  });
  await page.route('**/api/reports/replay/**', async (route) => {
    await fulfillJson(route, {
      session_id: E2E_SESSION_ID,
      report: null,
      citations: [],
      trace_digest: {},
    });
  });
  await page.route('**/api/execute**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `data: ${JSON.stringify({ type: 'done' })}\n\n`,
    });
  });
  await page.route('**/health', async (route) => {
    await fulfillJson(route, { status: 'ok' });
  });
});

test.afterEach(async ({ page }, testInfo) => {
  const path = testInfo.outputPath('final-state.png');
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach('final-state', { path, contentType: 'image/png' });
});

test('原始 AgentLogPanel 默认隐藏，仅在本地开发者标记下显示', async ({ page }) => {
  await page.goto('/dashboard/AAPL');
  await expect(page.getByTestId('context-panel-expand')).toBeVisible();
  await expect(page.getByText('Console', { exact: true })).toHaveCount(0);

  await page.evaluate(async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    localStorage.setItem('finsight_dev', '1');
    window.dispatchEvent(new Event('finsight-dev-mode-change'));
  });

  await expect(page.getByText('Console', { exact: true })).toBeVisible();
});

test('所属对话展示真实Agent活动，不把内部计划字段当作用户过程', async ({ page }) => {
  await page.route('**/api/execute', async (route) => {
    const request = route.request().postDataJSON();
    const frames = [
      { type: 'agent.started', agent_id: 'news-worker', payload: {
        role: 'news_agent', agent_label: '新闻分析师', task: '核实AAPL新闻', status: 'running', internal_diagnostic: 'fixture-internal-detail',
      } },
      { type: 'tool.started', agent_id: 'news-worker', payload: {
        name: 'get_company_news', tool_call_id: 'news-read', display: { title: '读取公司新闻', target: 'AAPL' },
      } },
      { type: 'tool.result', agent_id: 'news-worker', payload: {
        name: 'get_company_news', tool_call_id: 'news-read', status: 'ok',
        display: { title: '读取公司新闻', target: 'AAPL', status: 'ok', result: '已取得公司报道' },
      } },
      { type: 'agent.finished', agent_id: 'news-worker', payload: {
        role: 'news_agent', agent_label: '新闻分析师', status: 'completed', summary: '新闻分析已完成',
      } },
      { type: 'done', response: 'ok', run_status: 'completed' },
    ];
    const body = frames
      .map((frame, index) => `data: ${JSON.stringify({ ...frame, schema_version: frame.type === 'done' ? undefined : '2', run_id: request.run_id, session_id: request.session_id, seq: index + 1, stream_epoch: 'trace-v2' })}\n\n`)
      .join('');
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    });
  });

  await page.goto('/chat');
  await page.locator('#chat-input').fill('分析 AAPL 新闻');
  await page.getByTestId('chat-send-btn').click();
  await openResearchProcess(page);

  await expect(page.locator('.tool-activity-row').filter({ hasText: '新闻分析师' })).toBeVisible();
  await expect(page.getByText('fixture-internal-detail')).toHaveCount(0);
  await expect(page.getByTestId('context-tab-execution')).toHaveCount(0);
});

test('traceRawEnabled=false 时仍可见真实工具活动', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('finsight-trace-raw-enabled', 'false');
  });

  await page.route('**/api/execute', async (route) => {
    const request = route.request().postDataJSON();
    const frames = [
      { type: 'agent.started', agent_id: 'news-worker', payload: {
        role: 'news_agent', agent_label: '新闻分析师', task: '核实AAPL新闻', status: 'running', internal_diagnostic: 'fixture-internal-detail',
      } },
      { type: 'tool.started', agent_id: 'news-worker', payload: {
        name: 'get_company_news', tool_call_id: 'news-read', display: { title: '读取公司新闻', target: 'AAPL' },
      } },
      { type: 'tool.result', agent_id: 'news-worker', payload: {
        name: 'get_company_news', tool_call_id: 'news-read', status: 'ok',
        display: { title: '读取公司新闻', target: 'AAPL', status: 'ok', result: '已取得公司报道' },
      } },
      { type: 'agent.finished', agent_id: 'news-worker', payload: {
        role: 'news_agent', agent_label: '新闻分析师', status: 'completed', summary: '新闻分析已完成',
      } },
      { type: 'done', response: 'ok', run_status: 'completed' },
    ];
    const body = frames
      .map((frame, index) => `data: ${JSON.stringify({ ...frame, schema_version: frame.type === 'done' ? undefined : '2', run_id: request.run_id, session_id: request.session_id, seq: index + 1, stream_epoch: 'trace-v2' })}\n\n`)
      .join('');
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    });
  });

  await page.goto('/chat');
  await page.locator('#chat-input').fill('分析 AAPL 新闻');
  await page.getByTestId('chat-send-btn').click();
  await expect(page.getByText('ok', { exact: true })).toBeVisible();
  await openResearchProcess(page);
  const agentRow = page.locator('.tool-activity-row').filter({ hasText: '新闻分析师' });
  await expect(agentRow).toBeVisible();
  if (await agentRow.locator('..').getAttribute('open') === null) await agentRow.click();
  await expect(page.locator('.tool-activity-row').filter({ hasText: '读取公司新闻' })).toBeVisible();
  await expect(page.getByText('fixture-internal-detail')).toHaveCount(0);
  expect(await page.evaluate(async () => {
    const path = '/src/store/useStore.ts';
    const { useStore } = await import(path);
    return { rawEnabled: useStore.getState().traceRawEnabled, rawCount: useStore.getState().rawEvents.length };
  })).toEqual({ rawEnabled: false, rawCount: 0 });
});

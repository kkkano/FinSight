import { expect, test } from '@playwright/test';

const fulfillJson = async (route: any, payload: unknown) => {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
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
  await page.addInitScript(() => {
    localStorage.setItem('finsight-session-id', 'public:anonymous:e2e-trace');
    localStorage.setItem(
      'fs_dashboard_active_v1',
      JSON.stringify({ symbol: 'AAPL', type: 'equity', display_name: 'Apple' }),
    );
    localStorage.setItem('fs_dashboard_layout_v1', JSON.stringify({ hidden_widgets: [], order: [] }));
    localStorage.setItem('fs_dashboard_news_mode_v1', JSON.stringify('market'));
  });

  await page.route('**/api/dashboard**', async (route) => {
    const url = new URL(route.request().url());
    const symbol = url.searchParams.get('symbol') || 'AAPL';
    await fulfillJson(route, buildDashboardPayload(symbol));
  });
  await page.route('**/api/dashboard/insights**', async (route) => {
    await fulfillJson(route, {
      success: true,
      symbol: 'AAPL',
      insights: {},
      generated_at: new Date().toISOString(),
    });
  });
  await page.route('**/api/user/profile**', async (route) => {
    await fulfillJson(route, { profile: { name: 'E2E User', watchlist: ['AAPL'] } });
  });
  await page.route('**/api/subscriptions**', async (route) => {
    await fulfillJson(route, { subscriptions: [] });
  });
  await page.route('**/api/stock/price/**', async (route) => {
    await fulfillJson(route, { success: true, data: { price: 180.5, change_percent: 1.2 } });
  });
  await page.route('**/api/reports/index**', async (route) => {
    await fulfillJson(route, { success: true, session_id: 'public:anonymous:e2e-trace', count: 0, items: [] });
  });
  await page.route('**/api/reports/replay/**', async (route) => {
    await fulfillJson(route, {
      success: true,
      session_id: 'public:anonymous:e2e-trace',
      report: null,
      citations: [],
      trace_digest: {},
    });
  });
  await page.route('**/api/tasks/daily**', async (route) => {
    await fulfillJson(route, {
      success: true,
      session_id: 'public:anonymous:e2e-trace',
      tasks: [],
      count: 0,
    });
  });
  await page.route('**/chat/supervisor/stream**', async (route) => {
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

test('traceViewMode=dev 时展示原始 AgentLogPanel', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('finsight-trace-view-mode', 'dev');
  });
  await page.goto('/dashboard/AAPL');
  await expect(page.getByText('Console')).toBeVisible();
});

test('traceViewMode=expert 时展示执行面板并消费计划/决策事件', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('finsight-trace-view-mode', 'expert');
  });

  await page.route('**/api/execute', async (route) => {
    const frames = [
      { type: 'pipeline_stage', stage: 'planning', status: 'start', message: 'Planner started' },
      {
        type: 'plan_ready',
        plan_steps: [{ id: 's1', kind: 'agent', name: 'news_agent', optional: false }],
        selected_agents: ['news_agent'],
        skipped_agents: ['macro_agent'],
        has_parallel: false,
        reasoning_brief: 'Planner completed with one selected agent',
      },
      { type: 'pipeline_stage', stage: 'planning', status: 'done', message: 'Planner completed' },
      { type: 'pipeline_stage', stage: 'executing', status: 'start', message: 'Executor started' },
      { type: 'agent_start', agent: 'news_agent', status: 'running', step_id: 's1' },
      {
        type: 'agent_done',
        agent: 'news_agent',
        status: 'done',
        step_id: 's1',
        confidence: 0.82,
        evidence_count: 5,
        data_sources: ['reuters'],
        duration_ms: 950,
      },
      { type: 'step_done', step_id: 's1', kind: 'agent', name: 'news_agent', duration_ms: 950 },
      { type: 'pipeline_stage', stage: 'executing', status: 'done', message: 'Executor completed' },
      {
        type: 'decision_note',
        scope: 'planner',
        title: 'Planner selection summary',
        reason: 'Selected news_agent for current query',
        impact: 'parallel=no',
      },
      { type: 'pipeline_stage', stage: 'synthesizing', status: 'done', message: 'Synthesize completed' },
      { type: 'pipeline_stage', stage: 'rendering', status: 'done', message: 'Rendering completed' },
      { type: 'done', response: 'ok' },
    ];
    const body = frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('');
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    });
  });

  await page.goto('/workbench?symbol=AAPL');
  await page.getByRole('button', { name: '分析' }).click();

  await expect(page.getByText('计划摘要')).toBeVisible();
  await expect(page.getByText('决策说明', { exact: true })).toBeVisible();
  await expect(page.getByText('分组时间线')).toBeVisible();
  await expect(page.getByText('Agent 成功：1')).toBeVisible();
});

test('traceRawEnabled=false 时仍可见关键阶段进度', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('finsight-trace-view-mode', 'expert');
    localStorage.setItem('finsight-trace-raw-enabled', 'false');
  });

  await page.route('**/api/execute', async (route) => {
    const frames = [
      { type: 'pipeline_stage', stage: 'planning', status: 'start', message: 'Planner started' },
      {
        type: 'plan_ready',
        plan_steps: [{ id: 's1', kind: 'agent', name: 'news_agent', optional: false }],
        selected_agents: ['news_agent'],
        skipped_agents: ['macro_agent'],
        has_parallel: false,
        reasoning_brief: 'Planner selected one agent.',
      },
      { type: 'pipeline_stage', stage: 'planning', status: 'done', message: 'Planner completed' },
      { type: 'pipeline_stage', stage: 'executing', status: 'start', message: 'Executor started' },
      {
        type: 'decision_note',
        scope: 'planner',
        title: 'Planner selection summary',
        reason: 'macro agent skipped due scope',
      },
      { type: 'pipeline_stage', stage: 'executing', status: 'done', message: 'Executor completed' },
      { type: 'done', response: 'ok' },
    ];
    const body = frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('');
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    });
  });

  await page.goto('/workbench?symbol=AAPL');
  await page.getByRole('button', { name: '分析' }).click();

  await expect(page.getByText('Planner selection summary')).toBeVisible();
  await expect(page.getByText('Planner selected one agent.')).toBeVisible();
});

test('interrupt 事件会停在等待确认状态', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('finsight-trace-view-mode', 'expert');
  });

  await page.route('**/api/execute', async (route) => {
    const frames = [
      { type: 'pipeline_stage', stage: 'planning', status: 'start', message: 'Planner started' },
      {
        type: 'interrupt',
        thread_id: 'thread-1',
        prompt: 'Need confirmation to continue',
        options: ['continue', 'cancel'],
        required_agents: ['financial_agent'],
      },
    ];
    const body = frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('');
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    });
  });

  await page.goto('/workbench?symbol=AAPL');
  await page.getByRole('button', { name: '分析' }).click();

  await expect(page.getByText('Need confirmation to continue').first()).toBeVisible();
});

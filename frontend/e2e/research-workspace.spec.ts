import { expect, test, type Page, type Route } from '@playwright/test';
import { makeEmptyTrackRecordFixture, makeTrackRecordFixture } from '../src/pages/trackRecord.fixtures';
import { installAuthenticatedSession } from './helpers/auth';

const prediction = {
  prediction_id: '00000000-0000-4000-8000-000000000101', run_id: 'workspace-fixture-run', symbol: 'AAPL',
  direction: 'short', status: 'waiting', agent: 'prediction_analyst', source_type: 'ai', confidence: 0.58,
  thesis: '测试判断：趋势仍向上，但 RSI 89.86 显示短线超买，等待冲高失败后回落至目标区域。',
  anchor: { timeframe: '1d', time: '2026-10-01', price: 333.26 }, entry: 333, stop: 338.2,
  target1: 325.2, target2: 318.6, invalidation_price: 339, prompt_version: 'workspace-fixture-v1',
  created_at: '2026-10-01T13:00:00Z', updated_at: '2026-10-01T13:00:00Z',
  evidence_provider: 'fixture-source', evidence_as_of: '2026-10-01T20:00:00Z',
  scenarios: [{ name: '回落情景', probability: 60, invalidation: '站稳失效价则结束假设' }, { name: '延续情景', probability: 40, invalidation: '跌破支撑' }],
};
const technicals = { close: 333.26, ma5: 330, ma10: 320, ma20: 310, ma50: 300, ma100: 290, ma200: 280,
  ema12: 325, ema26: 315, rsi: 89.86, macd_hist: -1, stoch_k: 50, cci: 0, trend: 'bullish', momentum: 'bearish', support_levels: [], resistance_levels: [] };
const bars = Array.from({ length: 260 }, (_, index) => ({ time: new Date(Date.UTC(2025, 9, 2 + index)).toISOString().slice(0, 10),
  open: 220 + index * 0.4, close: 222 + index * 0.4, high: 225 + index * 0.4, low: 217 + index * 0.4, volume: 40000000 + index * 10000 }));
const json = (route: Route, body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });

async function setup(page: Page, authenticated = true, ended = false) {
  const privateRequests: string[] = [];
  const ledgerRequests: URL[] = [];
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem('finsight-theme', 'light');
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  });
  if (authenticated) await installAuthenticatedSession(page);
  await page.route('**/health', (route) => json(route, { status: 'healthy' }));
  await page.route('**://*/api/**', (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (!path.startsWith('/api/')) return route.fallback();
    const outcome = ended ? { status: 'hit_target', pct_since_anchor: -2, evaluated_through: '2026-10-02T20:00:00Z', resolved_at: '2026-10-02T20:00:00Z', algorithm_version: 'fixture-v1' } : null;
    if (path.startsWith('/api/predictions/')) privateRequests.push(url.toString());
    if (path === '/api/predictions/latest') return json(route, { prediction, outcome });
    if (path === '/api/predictions/history') return json(route, { items: [{ prediction, outcome }] });
    if (path === '/api/predictions/stats') return json(route, { stats: { predictions: 1, resolved: ended ? 1 : 0, hits: ended ? 1 : 0,
      misses: 0, invalidated: 0, hit_rate: ended ? 1 : null, by_source: { ai: { predictions: 1, resolved: ended ? 1 : 0, hits: ended ? 1 : 0, misses: 0, invalidated: 0, hit_rate: ended ? 1 : null } } } });
    if (path.startsWith('/api/predictions/runs/')) return json(route, { run: { status: 'succeeded', llm_model: 'step-5-preview', llm_provider: 'stepfun', market_provider: 'fixture-source' } });
    if (path === '/api/benchmarks/us20-v1/track-record') {
      ledgerRequests.push(url);
      const data = authenticated ? makeTrackRecordFixture() : makeEmptyTrackRecordFixture();
      const records = data.records.filter((record) => (!url.searchParams.get('ticker') || record.ticker === url.searchParams.get('ticker'))
        && (!url.searchParams.get('status') || record.status === url.searchParams.get('status'))
        && (!url.searchParams.get('prediction_type') || record.prediction_type === url.searchParams.get('prediction_type')));
      const offset = Number(url.searchParams.get('offset') || 0);
      const limit = Number(url.searchParams.get('limit') || 20);
      return json(route, { ...data, records: records.slice(offset, offset + limit), pagination: { offset, limit, total: records.length, has_more: offset + limit < records.length } });
    }
    if (path.startsWith('/api/stock/kline/')) return json(route, { data: { kline_data: bars, quality: 'trusted', provider: 'fixture-source', source: 'fixture-source', as_of: '2026-10-01T20:00:00Z' } });
    if (path === '/api/dashboard') return json(route, { state: { active_asset: { symbol: 'AAPL', display_name: 'Apple', type: 'equity' }, capabilities: {} },
      data: { technicals, snapshot: {}, charts: {}, valuation: {}, meta: { technicals: { provider: 'fixture-source', as_of: '2026-10-01T20:00:00Z' } } } });
    if (path === '/api/monitor/comments/stream') return route.fulfill({ status: 503, body: '{}' });
    if (path === '/api/models') return json(route, { models: [], default_model_id: null });
    return json(route, { items: [], messages: [], count: 0, data: {}, profile: {} });
  });
  return { privateRequests, ledgerRequests };
}

test('战绩进入独立页面，公开账本可筛选和查看明细', async ({ page }, testInfo) => {
  const requests = await setup(page, true, true);
  await page.goto('/dashboard/AAPL');
  await page.getByTestId('sidebar-nav-track-record').click();
  await expect(page).toHaveURL(/\/track-record$/);
  await expect(page.getByTestId('direction-results')).toContainText('25.0%');
  await page.getByLabel('标的筛选', { exact: true }).selectOption('AAPL');
  await expect.poll(() => requests.ledgerRequests.at(-1)?.searchParams.get('ticker')).toBe('AAPL');
  await page.getByTestId('prediction-record-row').first().getByRole('button').click();
  await expect(page.getByTestId('benchmark-record-detail')).toContainText('实际对账行情');
  await page.screenshot({ path: testInfo.outputPath('workspace-track-record.png') });
});

test('手机公开战绩不读取个人记录', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await setup(page, false);
  await page.goto('/track-record');
  await expect(page.getByTestId('us20-track-record')).toContainText('预测采集尚未开启');
  expect(requests.privateRequests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('workspace-track-mobile.png') });
});

test('技术页保留真实指标和已验证预测图层', async ({ page }, testInfo) => {
  await setup(page);
  await page.goto('/dashboard/AAPL?tab=technical');
  await expect(page.getByText('指标多数偏多', { exact: true })).toBeVisible();
  await expect(page.getByText('日线均线与动量指标的当前状态统计，不是未来涨跌预测。')).toBeVisible();
  await expect(page.getByText(/RSI 89\.9 处于超买区/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('workspace-judgment-meaning.png') });
});

test('个股个人记录与公开基准保持独立', async ({ page }) => {
  await setup(page, true, true);
  await page.goto('/track-record?ticker=AAPL&scope=personal');
  await expect(page.getByRole('heading', { name: 'AAPL预测记录' })).toBeVisible();
  await expect(page.getByTestId('personal-track-record')).toBeVisible();
  await expect(page.getByTestId('benchmark-track-record-content')).toHaveCount(0);
});

test('标的面板单列展示236px图，周期与图型可切换，窄屏可关闭', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await setup(page);
  await page.goto('/dashboard/AAPL');
  await page.getByTestId('context-panel-expand').click();
  const panel = page.getByTestId('context-panel');
  await expect(panel.getByRole('button', { name: '3月', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const chart = panel.getByTestId('context-chart-surface');
  await expect(chart.locator('canvas, svg').first()).toBeVisible();
  await expect(chart).toHaveCSS('height', '236px');
  await panel.getByRole('button', { name: '1月', exact: true }).click();
  await expect(panel.getByRole('button', { name: '1月', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await panel.getByRole('button', { name: '折线', exact: true }).click();
  await expect(panel.getByRole('button', { name: '折线', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(panel.getByRole('tab')).toHaveCount(0);
  await page.setViewportSize({ width: 1100, height: 960 });
  const drawer = page.getByRole('dialog', { name: '研究侧栏', exact: true });
  await expect(drawer).toBeVisible();
  expect((await drawer.boundingBox())?.width).toBe(420);
  await page.screenshot({ path: testInfo.outputPath('workspace-chart-drawer.png') });
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
});

test('实际工具过程保留在所属对话，不占用标的面板', async ({ page }, testInfo) => {
  await setup(page);
  await page.goto('/chat');
  await page.evaluate(async () => {
    const { useStore } = await import('/src/store/useStore.ts');
    const timestamp = Date.now();
    useStore.setState({ currentTicker: 'AAPL', messages: [
      { id: 'fixture-user', role: 'user', content: '分析 AAPL', timestamp },
      { id: 'fixture-answer', role: 'assistant', content: '已核对行情。', timestamp, runId: 'fixture-run', runStatus: 'completed',
        thinking: [
          { stage: 'tool_start', timestamp: new Date(timestamp).toISOString(), result: { name: 'get_stock_price', tool_call_id: 'price', seq: 1 } },
          { stage: 'tool_end', timestamp: new Date(timestamp + 1200).toISOString(), result: { name: 'get_stock_price', tool_call_id: 'price', duration_ms: 1200,
            display: { target: 'AAPL', result: '已取得收盘价' }, seq: 2 } },
        ] },
    ] });
  });
  await page.getByRole('button', { name: /已处理.*1 次工具调用/ }).click();
  await expect(page.locator('.tool-activity-row')).toContainText('获取行情');
  await page.getByTestId('context-panel-expand').click();
  const panel = page.getByTestId('context-panel');
  await expect(panel.getByRole('tab')).toHaveCount(0);
  await expect(panel.getByText('执行详情', { exact: true })).toHaveCount(0);
  expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('workspace-progress.png') });
});

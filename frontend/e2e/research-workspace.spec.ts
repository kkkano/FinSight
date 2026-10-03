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
  await page.route('**/api/**', (route) => {
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

test('战绩在当前工作区右侧打开，账本独立且可查看明细', async ({ page }, testInfo) => {
  const requests = await setup(page, true, true);
  await page.goto('/dashboard/AAPL');
  await page.getByTestId('sidebar-nav-track-record').click();
  await expect(page).toHaveURL(/\/dashboard\/AAPL$/);
  const drawer = page.getByRole('dialog', { name: '研究侧栏', exact: true });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('tab', { name: '我的判断', exact: true })).toHaveAttribute('aria-selected', 'true');
  await drawer.getByTestId('personal-record-row').click();
  await expect(drawer.getByTestId('personal-record-detail')).toContainText('原判断：回落假设');
  await expect(drawer.getByTestId('personal-record-detail')).toContainText('不代表当前观点');
  await drawer.getByRole('tab', { name: 'US20 基准', exact: true }).click();
  await expect(drawer.getByTestId('direction-results')).toContainText('25.0%');
  const tickerFilter = drawer.getByLabel('US20 标的筛选');
  await tickerFilter.selectOption('AAPL');
  await expect.poll(() => requests.ledgerRequests.at(-1)?.searchParams.get('ticker')).toBe('AAPL');
  await drawer.getByTestId('prediction-record-row').first().click();
  await expect(drawer.getByTestId('benchmark-record-detail')).toContainText('实际结果');
  await page.screenshot({ path: testInfo.outputPath('workspace-track-record.png') });
  await page.keyboard.press('Escape');
  await expect(drawer).not.toBeVisible();
  await expect(page.getByTestId('sidebar-nav-track-record')).toBeFocused();
});

test('手机战绩全屏且匿名不读取个人记录', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await setup(page, false);
  await page.goto('/today');
  await page.getByTestId('sidebar-nav-track-record').click();
  const drawer = page.getByRole('dialog', { name: '研究侧栏', exact: true });
  await expect(drawer.getByRole('tab', { name: 'US20 基准', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(drawer.getByTestId('us20-track-record')).toContainText('固定采集尚未启用');
  expect((await drawer.boundingBox())?.width).toBe(390);
  await drawer.getByRole('tab', { name: '我的判断', exact: true }).click();
  await expect(drawer.getByTestId('personal-track-record-login')).toBeVisible();
  expect(requests.privateRequests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('workspace-track-mobile.png') });
});

test('当前技术状态与AI回落假设写清楚各自口径', async ({ page }, testInfo) => {
  await setup(page);
  await page.goto('/dashboard/AAPL');
  const judgment = page.getByTestId('prediction-track');
  await expect(judgment).toContainText('AI 回落假设');
  await expect(judgment).toContainText('满足入场条件后');
  await expect(judgment).toContainText('未声明固定天数');
  await expect(page.getByText('指标多数偏多', { exact: true })).toBeVisible();
  await expect(page.getByText('日线均线与动量指标的当前状态统计，不是未来涨跌预测。')).toBeVisible();
  await expect(page.getByText(/RSI 89\.9 处于超买区/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('workspace-judgment-meaning.png') });
});

test('已结束的AI判断默认收进历史，展开保留依据', async ({ page }) => {
  await setup(page, true, true);
  await page.goto('/dashboard/AAPL');
  const judgment = page.getByTestId('prediction-track');
  await expect(judgment).toContainText('最近已结束判断');
  await expect(judgment).toContainText('当前没有新的有效 AI 判断');
  await expect(judgment.getByText(prediction.thesis, { exact: true })).not.toBeVisible();
  await judgment.getByText('历史判断与价位', { exact: true }).click();
  await expect(judgment.getByText(prediction.thesis, { exact: true })).toBeVisible();
});

test('侧栏图表比例稳定，周期可切换，嵌套弹窗关闭不误关抽屉', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await setup(page);
  await page.goto('/dashboard/AAPL');
  await page.getByTestId('context-panel-expand').click();
  const panel = page.getByTestId('context-panel');
  await expect(panel.getByRole('button', { name: '3 月', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const chart = panel.getByTestId('context-chart-surface').locator('.echarts-for-react');
  await expect(chart.locator('canvas, svg').first()).toBeVisible();
  const box = await chart.boundingBox();
  expect(box?.height).toBeGreaterThan(200);
  expect(box?.height).toBeLessThan(341);
  await panel.getByRole('button', { name: '1 月', exact: true }).click();
  await expect(panel.getByRole('button', { name: '1 月', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await panel.getByRole('button', { name: '展开详情', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: '研究侧栏', exact: true });
  expect((await drawer.boundingBox())?.width).toBe(640);
  await drawer.getByRole('button', { name: '1 年', exact: true }).click();
  await drawer.getByRole('button', { name: '放大行情图', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'AAPL 行情', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'AAPL 行情', exact: true })).not.toBeVisible();
  await expect(drawer).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('workspace-chart-drawer.png') });
});

test('进度摘要统计不挤压，详细瀑布折叠且识别最慢步骤', async ({ page }, testInfo) => {
  await setup(page);
  await page.goto('/dashboard/AAPL');
  await page.evaluate(async () => {
    const modulePath = '/src/store/executionStore.ts';
    const { useExecutionStore } = await import(modulePath);
    const startedAt = new Date(Date.now() - 82000).toISOString();
    const timestamp = new Date().toISOString();
    useExecutionStore.setState({ activeRuns: [{ runId: 'fixture-run', query: '模拟验收分析', tickers: ['AAPL'], source: 'fixture', outputMode: 'chat',
      status: 'running', progress: 75, currentStep: '正在合成判断', startedAt, completedAt: null, report: null, error: null, fallbackReasons: [], streamedContent: '',
      agentStatuses: { technical: { name: 'technical', status: 'done' } }, selectedAgents: ['technical'], skippedAgents: [], decisionNotes: [],
      planSteps: [{ id: 'price', kind: 'tool', name: 'get_stock_price' }],
      timeline: [{ id: 's', eventType: 'step_start', stage: 'executing', stepId: 'price', kind: 'tool', name: 'get_stock_price', timestamp: startedAt },
        { id: 'e', eventType: 'step_done', stage: 'executing', stepId: 'price', kind: 'tool', name: 'get_stock_price', timestamp, durationMs: 69670, status: 'done' }],
    }] });
  });
  await page.getByTestId('context-panel-expand').click();
  await page.getByTestId('context-tab-execution').click();
  const panel = page.getByTestId('context-panel');
  await expect(panel).toContainText('get_stock_price');
  await expect(panel).toContainText('最耗时');
  await expect(panel.getByText('并行执行瀑布', { exact: true })).not.toBeVisible();
  await panel.getByText('执行详情', { exact: true }).click();
  await expect(panel.getByText('并行执行瀑布', { exact: true })).toBeVisible();
  expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('workspace-progress.png') });
});

import { expect, test, type Page, type Route } from '@playwright/test';

import { installAuthenticatedSession } from './helpers/auth';

const prediction = {
  prediction_id: '00000000-0000-4000-8000-000000000001',
  run_id: 'readability-run',
  symbol: 'AAPL',
  direction: 'short',
  status: 'hit_target',
  source_type: 'ai',
  agent: 'prediction_analyst',
  thesis: 'AAPL 已处于强势上升后的极度超买区。收盘 333.26 接近布林上轨 334.79，RSI 89.86；随机指标与 Williams %R 均显示短线过热，ADX 虽确认趋势强，但当前更像加速段末端。若无法快速站稳 334.79 上方并延续放量突破，需观察获利回吐风险。当前更适合等待冲高失败后的均值回归，短线回落观察 328 / 324 区域。',
  confidence: 58,
  anchor: { timeframe: '1d', time: '2026-09-30', price: 333.26 },
  entry: 333,
  stop: 338.2,
  target1: 325.2,
  target2: 318.6,
  scenarios: [
    { name: '冲高后回落确认', probability: 38, invalidation: '若日内或次日有效站稳 336.36 并继续放量突破 339.47，则回撤逻辑失效。' },
    { name: '高位横盘后跌破支撑', probability: 34, invalidation: '若价格始终守住 328.47 并重新上攻前高，说明卖压不足。' },
    { name: '放量继续突破', probability: 0.5, invalidation: '若突破 334.79 后快速扩展至 339.47 上方，短线回撤预期失效。' },
  ],
  prompt_version: 'prediction-analyst-v1',
  evidence_provider: 'twelve_data',
  evidence_as_of: '2026-09-30T20:00:00Z',
  created_at: '2026-10-01T00:00:00Z',
};
const outcome = {
  status: 'hit_target', pct_since_anchor: -2.001,
  evaluated_through: '2026-10-01T20:00:00Z', algorithm_version: 'prediction-outcome-v1',
};
const run = { run_id: 'readability-run', status: 'succeeded', llm_provider: 'openai_compatible', llm_model: 'step-5-preview', market_provider: 'twelve_data' };
const bars = Array.from({ length: 260 }, (_, index) => {
  const date = new Date(Date.UTC(2025, 9, 2 + index));
  const close = 220 + index * 0.42 + Math.sin(index / 12) * 12;
  return { time: date.toISOString().slice(0, 10), open: close - 1.5, close, high: close + 3, low: close - 4, volume: 50000000 + index * 50000 };
});

const json = (route: Route, body: unknown) => route.fulfill({
  status: 200, contentType: 'application/json', body: JSON.stringify(body),
});

async function installFixtures(page: Page, theme: 'dark' | 'light', empty = false) {
  await page.addInitScript((value) => {
    localStorage.clear();
    localStorage.setItem('finsight-theme', value);
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  }, theme);
  await installAuthenticatedSession(page);
  await page.route('**/health', (route) => json(route, { status: 'healthy' }));
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.fallback();
    if (path === '/api/predictions/history') return json(route, { items: empty ? [] : [{ prediction, outcome }, { prediction: { ...prediction, symbol: 'AAOI', prediction_id: '00000000-0000-4000-8000-000000000002' }, outcome }] });
    if (path === '/api/predictions/stats') return json(route, { stats: { predictions: empty ? 0 : 2, resolved: empty ? 0 : 2, hits: empty ? 0 : 1, misses: empty ? 0 : 1, invalidated: 0, hit_rate: empty ? null : 0.5 } });
    if (path === '/api/predictions/latest') return json(route, { prediction: empty ? null : prediction, outcome });
    if (path.startsWith('/api/predictions/runs/')) return json(route, { run });
    if (path.startsWith('/api/stock/kline/')) return json(route, { data: { kline_data: bars, source: 'twelve_data', provider: 'twelve_data', quality: 'trusted', as_of: '2026-10-01T20:00:00Z' } });
    if (path === '/api/dashboard') return json(route, {
      state: { active_asset: { symbol: 'AAPL', display_name: 'Apple Inc.', type: 'equity' }, capabilities: {} },
      data: { snapshot: { price: 333.26, change_percent: -2.001 }, charts: {}, valuation: {} },
    });
    if (path === '/api/monitor/comments/stream') return route.fulfill({
      status: 200, contentType: 'text/event-stream', body: `event: snapshot\ndata: ${JSON.stringify([
        { id: 'error-1', symbol: 'AAPL', ts: '2026-10-01T00:37:00Z', level: 'error', text: '实时点评生成失败: InternalServerError', trigger: { kind: 'price_change', detail: 'AAPL 达到 300 秒检查窗口，最新价 333.08' }, escalated: false },
        { id: 'info-1', symbol: 'AAPL', ts: '2026-10-01T00:35:00Z', level: 'info', text: '价格仍在观察区间内。', trigger: { kind: 'heartbeat', detail: '无显著变化' }, escalated: false },
      ])}\n\n`,
    });
    if (path === '/api/monitor/leases') return json(route, { lease: { id: 'lease-1', lease_token: 'fixture', symbol: 'AAPL' } });
    if (path === '/api/user/profile') return json(route, { profile: {} });
    if (path.startsWith('/api/stock/price/')) return json(route, { data: { data: { price: 333.26, change_percent: -2.001 }, provider: 'twelve_data', as_of: '2026-10-01T20:00:00Z' } });
    return json(route, { items: [], messages: [], count: 0 });
  });
}

async function expectNoHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
}

for (const [width, height, theme] of [[1440, 1000, 'dark'], [768, 1024, 'light'], [390, 844, 'dark']] as const) {
  test(`历史详情清晰且可滚动 ${width} ${theme}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await installFixtures(page, theme);
    await page.goto('/history');
    const detail = page.getByTestId('prediction-history-detail');
    await expect(detail).toContainText('-2.0%');
    await expect(detail).not.toContainText('-200.1%');
    await expect(detail).toContainText('0.5%');
    await detail.getByText('放量继续突破').scrollIntoViewIfNeeded();
    await expect(detail.getByText('放量继续突破')).toBeInViewport();
    await expect(detail.getByText('step-5-preview', { exact: false })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.getByTestId('prediction-history-item').nth(1).click();
    await expect(detail.getByRole('heading', { name: 'AAOI', exact: true })).toBeVisible();
    if (width >= 1024) await expect(detail.getByRole('heading', { name: 'AAOI', exact: true })).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath(`history-${width}-${theme}.png`) });
  });
}

for (const width of [1440, 390]) {
  test(`看板正文与异常详情可读 ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await installFixtures(page, 'dark');
    await page.goto('/dashboard/AAPL');
    const panel = page.getByTestId('prediction-track');
    await panel.getByText('历史判断与价位', { exact: true }).click();
    await expect(panel).toContainText('极度超买区');
    expect(await panel.getByTestId('prediction-thesis').evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(14);
    await panel.getByText('证据与模型来源').click();
    await expect(panel).toContainText('step-5-preview');
    const feed = page.getByTestId('monitor-activity-feed');
    await feed.getByText('错误详情').click();
    await expect(feed.getByText('实时点评生成失败: InternalServerError', { exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`dashboard-${width}.png`) });
  });

  test(`放大行情占满主体并支持关闭 ${width}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await installFixtures(page, 'dark');
    await page.goto('/dashboard/AAPL');
    await page.getByTestId('context-panel-expand').click();
    await page.getByTestId('context-panel').getByRole('button', { name: '1 年', exact: true }).click();
    const trigger = page.getByRole('button', { name: '放大行情图', exact: true });
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: 'AAPL 行情' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('收盘', { exact: true })).toBeVisible();
    const canvas = dialog.locator('canvas').first();
    await expect(canvas).toBeVisible();
    await expect.poll(async () => (await canvas.boundingBox())?.height ?? 0).toBeGreaterThan(500);
    const pixels = await canvas.evaluate((element) => {
      const canvasElement = element as HTMLCanvasElement;
      const data = canvasElement.getContext('2d')!.getImageData(0, 0, canvasElement.width, canvasElement.height).data;
      let colorful = 0;
      let volumeColorful = 0;
      for (let index = 0; index < data.length; index += 16) {
        if (data[index + 3] && Math.max(data[index], data[index + 1], data[index + 2]) - Math.min(data[index], data[index + 1], data[index + 2]) > 35) {
          colorful++;
        }
        const y = Math.floor(index / 4 / canvasElement.width);
        const x = (index / 4) % canvasElement.width;
        if (data[index + 3] > 80 && data[index] > 120 && x > canvasElement.width * 0.2
          && y > canvasElement.height * 0.7 && y < canvasElement.height * 0.88) volumeColorful++;
      }
      return { colorful, volumeColorful };
    });
    expect(pixels.colorful).toBeGreaterThan(200);
    expect(pixels.volumeColorful).toBeGreaterThan(100);
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`chart-${width}.png`) });
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(trigger).toBeFocused();
  });
}

test('历史空状态不显示虚构命中率', async ({ page }) => {
  await installFixtures(page, 'light', true);
  await page.goto('/history');
  await expect(page.getByText('暂无 AI 判断记录')).toBeVisible();
  await expect(page.getByText('暂无已结算样本')).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

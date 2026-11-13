import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { makeEmptyTrackRecordFixture, makePendingTrackRecordFixture, makeTrackRecordFixture } from '../src/pages/trackRecord.fixtures';
import type { PredictionTrackRecord } from '../src/types/predictions';

test.beforeEach(async ({ page }) => {
  await page.context().route('**/*', (route) => {
    const url = new URL(route.request().url());
    return ['127.0.0.1', 'localhost'].includes(url.hostname) ? route.fallback() : route.abort('blockedbyclient');
  });
  await page.context().route('**/sw.js*', (route) => route.fulfill({
    contentType: 'application/javascript', body: "self.addEventListener('install', () => self.skipWaiting());",
  }));
  await page.route('**/src/api/supabaseClient.ts*', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: 'export const getSupabaseClient = () => null; export const isSupabaseAuthConfigured = () => false;',
  }));
  await page.route('**/api/**', (route) => {
    if (!new URL(route.request().url()).pathname.startsWith('/api/')) return route.fallback();
    return route.fulfill({ contentType: 'application/json', body: '{"success":true,"items":[],"models":[],"data":{}}' });
  });
  await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"healthy"}' }));
});

test.afterEach(async ({ page }, testInfo) => {
  const path = testInfo.outputPath('final-state.png');
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach('final-state', { path, contentType: 'image/png' });
});

// 所有返回值都是明确标记的界面测试样本，不代表真实战绩。
async function mockLedger(page: Page, getData: () => PredictionTrackRecord, fail?: () => boolean) {
  const headers: Array<Record<string, string>> = [];
  await page.route('**/api/benchmarks/us20-v1/track-record?*', async (route) => {
    headers.push(route.request().headers());
    const data = getData();
    const params = new URL(route.request().url()).searchParams;
    const limit = Number(params.get('limit') || 20);
    const offset = Number(params.get('offset') || 0);
    const records = data.records.filter((record) =>
      (!params.get('ticker') || record.ticker === params.get('ticker'))
      && (!params.get('status') || record.status === params.get('status'))
      && (!params.get('prediction_type') || record.prediction_type === params.get('prediction_type')));
    await route.fulfill({
      status: fail?.() ? 503 : 200,
      contentType: 'application/json',
      body: JSON.stringify(fail?.() ? { detail: 'fixture-internal-error' } : {
        ...data, records: records.slice(offset, offset + limit),
        pagination: { limit, offset, total: records.length, has_more: offset + limit < records.length },
      }),
    });
  });
  return headers;
}

test('public empty and pending states require no welcome gate and never invent hit rates', async ({ page }) => {
  let fixture = makeEmptyTrackRecordFixture();
  const headers = await mockLedger(page, () => fixture);
  await page.goto('/track-record');
  await expect(page).toHaveURL(/\/track-record$/);
  await expect(page.getByRole('heading', { name: '预测战绩', exact: true })).toBeVisible();
  await expect(page.getByText('自动预测暂停中，以前的记录照常可查。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('direction-results').getByText('等待首批对账', { exact: true })).toBeVisible();
  await expect(page.getByTestId('drawdown-results').getByText('等待首批对账', { exact: true })).toBeVisible();
  await expect(page.getByText('AI 命中率', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => sessionStorage.getItem('finsight-welcome-gate-passed'))).toBeNull();

  fixture = makePendingTrackRecordFixture();
  await page.getByRole('button', { name: '刷新战绩' }).click();
  const rules = page.locator('summary').filter({ hasText: '统计口径' });
  await expect(rules).toBeVisible();
  await rules.click();
  await expect(page.getByText('实际发布 40 条，应发布 40 条。', { exact: false })).toBeVisible();
  await expect(page.getByTestId('prediction-record-row')).toHaveCount(20);
  await expect(page.getByText('AI 命中率', { exact: true })).toHaveCount(0);
  await expect(page.getByTestId('prediction-record-row').filter({ hasText: '等待对账' })).toHaveCount(20);
  await page.getByTestId('prediction-record-row').first().getByRole('button').click();
  await expect(page.getByTestId('benchmark-record-detail')).toContainText('尚未完成对账');
  await expect(page.getByTestId('benchmark-record-detail')).not.toContainText('100.0%');
  await page.getByTestId('prediction-record-row').first().getByRole('button').click();
  for (const requestHeaders of headers) {
    expect(requestHeaders.authorization).toBeUndefined();
    expect(requestHeaders['x-finsight-model']).toBeUndefined();
  }
  await page.getByTestId('sidebar-nav-chat').click();
  await expect(page).toHaveURL(/\/welcome(?:\?|$)/);
});

test('settled fixtures retain losing groups, unknown models and all failure statuses on desktop and mobile', async ({ page }, testInfo) => {
  const fixture = makeTrackRecordFixture();
  // 小样本提示由接口元数据给出阈值，不依赖页面暗含默认值。
  fixture.metadata.min_sample_size = 30;
  Object.assign(fixture, { endpoint_url: 'https://private-endpoint.fixture', session_id: 'private-session-fixture', raw_reasoning: 'private-raw-thoughts-fixture' });
  await mockLedger(page, () => fixture);
  await page.goto('/track-record');
  const rules = page.locator('summary').filter({ hasText: '统计口径' });
  await expect(rules).toBeVisible();
  await rules.click();
  await expect(page.getByText('fixture-固定样本-v1', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('实际发布 36 条，应发布 40 条。', { exact: false })).toBeVisible();
  const direction = page.getByTestId('direction-results');
  await expect(direction.getByText('25.0%', { exact: true })).toBeVisible();
  await expect(direction).toContainText('“永远猜涨”的命中率：75.0%');
  await expect(direction.getByTestId('prediction-baseline-delta').first()).toContainText('低 50.0 个百分点');
  await expect(page.getByTestId('direction-unconfirmed-models')).toContainText('模型身份未确认的记录');
  await expect(direction).toContainText('4 次已对账中猜中 1 次');
  await expect(direction.getByText('样本还少，先别当真', { exact: true })).toBeVisible();
  const risk = page.getByTestId('drawdown-results');
  await expect(risk).toContainText('0 / 1');
  await expect(risk).toContainText('1 次真实大跌里，提前预警了 0 次');
  await expect(risk).toContainText('另有 1 次预警了但没跌');
  const confusion = page.locator('section').filter({ has: page.getByRole('heading', { name: '大跌预警的对错', exact: true }) });
  for (const [label, count] of [['报对了', 0], ['虚惊', 1], ['正确放过', 3], ['漏报', 1]] as const) {
    await expect(confusion.locator('.track-record-cell').filter({ has: page.getByText(label, { exact: true }) }).locator('.num')).toHaveText(String(count));
  }
  const rows = page.getByTestId('prediction-record-row');
  await expect(rows).toHaveCount(20);
  await page.getByLabel('状态筛选', { exact: true }).selectOption('settled');
  await expect(rows).toHaveCount(10);
  await expect(rows.filter({ hasText: /没猜中|虚惊|漏报/ })).toHaveCount(6);
  await expect(direction.getByText('25.0%', { exact: true })).toBeVisible();
  await rows.first().getByRole('button').click();
  await expect(page.getByTestId('benchmark-record-detail')).toContainText('当时的判断');
  await expect(page.getByTestId('benchmark-record-detail')).toContainText('后来怎么走的');
  await expect(page.getByTestId('benchmark-record-detail')).toContainText('fixture-model-a');
  await rows.first().getByRole('button').click();
  for (const [status, count] of [['failed', 2], ['awaiting_data', 2], ['missed', 1], ['abstained', 1]] as const) {
    await page.getByLabel('状态筛选', { exact: true }).selectOption(status);
    await expect(rows).toHaveCount(count);
  }
  await page.getByLabel('状态筛选', { exact: true }).selectOption('failed');
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText('发布失败，不计入');
  await rows.first().getByRole('button').click();
  await expect(page.getByTestId('benchmark-record-detail')).toContainText('这条没法评分');
  await rows.first().getByRole('button').click();
  await page.getByLabel('状态筛选', { exact: true }).selectOption('');
  await page.getByLabel('标的筛选', { exact: true }).selectOption('AAPL');
  await page.getByLabel('预测类型筛选', { exact: true }).selectOption('drawdown');
  await expect(rows).toHaveCount(1);
  await expect(rows.first().getByRole('button', { name: 'AAPL', exact: true })).toBeVisible();
  await expect(rows.first()).toContainText('大跌预警');
  await expect(direction.getByText('25.0%', { exact: true })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('private-endpoint.fixture');
  await expect(page.locator('body')).not.toContainText('private-session-fixture');
  await expect(page.locator('body')).not.toContainText('private-raw-thoughts-fixture');
  await page.getByRole('heading', { name: '预测战绩', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('track-record-desktop-fixture.png') });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('heading', { name: '预测战绩', exact: true }).scrollIntoViewIfNeeded();
  await expect(page.getByRole('heading', { name: '预测战绩', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('track-record-mobile-fixture.png') });
});

test('a failed public read offers retry without manufacturing an empty result', async ({ page }) => {
  let failing = true;
  await mockLedger(page, makeEmptyTrackRecordFixture, () => failing);
  await page.goto('/track-record');
  await expect(page.getByRole('alert')).toContainText('战绩没加载出来，点刷新再试一次。');
  await expect(page.getByText('已结算 · 成熟样本', { exact: true })).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('fixture-internal-error');
  failing = false;
  await page.getByRole('button', { name: '刷新战绩' }).click();
  await expect(page.getByText('自动预测暂停中，以前的记录照常可查。', { exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('pagination reaches older settled fixtures beyond 200 records and retains the current page on failure', async ({ page }) => {
  const pending = makePendingTrackRecordFixture();
  const settled = makeTrackRecordFixture();
  const windows = [
    ['2026-09-30', '2026-10-06'], ['2026-09-29', '2026-10-05'],
    ['2026-09-28', '2026-10-02'], ['2026-09-25', '2026-10-01'],
    ['2026-09-24', '2026-09-30'], ['2026-09-23', '2026-09-29'],
  ];
  const records = [
    ...windows.flatMap(([start, end], batchIndex) => pending.records.map((record, index) => ({
      ...record, id: `fixture-${batchIndex}-${String(index).padStart(3, '0')}`,
      batch_date: start, window_start: start, window_end: end, issued_at: `${start}T13:00:00Z`,
    }))),
    ...settled.records.filter((record) => record.status === 'settled').map((record) => ({
      ...record, reason: '测试 fixture：较早已结算记录，非真实战绩。',
    })),
  ];
  const summary = {
    ...pending.summary, opportunities: 250, predictions: 250, settled: 10, pending: 240, batch_count: 7,
  };
  const offsets: number[] = [];
  let failNextPage = true;
  await page.route('**/api/benchmarks/us20-v1/track-record?*', async (route) => {
    const params = new URL(route.request().url()).searchParams;
    const offset = Number(params.get('offset') || 0);
    const limit = Number(params.get('limit') || 50);
    offsets.push(offset);
    if (offset === 20 && failNextPage) {
      failNextPage = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
      return;
    }
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        ...pending, summary, groups: settled.groups,
        coverage: { ...pending.coverage, batch_date: windows[0][0], last_update: '2026-09-30T13:00:00Z' },
        records: records.slice(offset, offset + limit),
        pagination: { offset, limit, total: records.length, has_more: offset + limit < records.length },
      }),
    });
  });

  await page.goto('/track-record');
  const range = page.getByTestId('prediction-page-range');
  await expect(range).toHaveText('第 1–20 条，共 250 条');
  await expect(page.getByRole('button', { name: '上一页预测明细', exact: true })).toBeDisabled();
  await expect(page.getByTestId('prediction-record-row').filter({ hasText: '已结算 ·' })).toHaveCount(0);
  await expect(page.getByTestId('direction-results').getByText('25.0%', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一页预测明细', exact: true }).click();
  await expect(page.getByText('刷新失败，下面是上次加载的结果。')).toBeVisible();
  await expect(range).toHaveText('第 1–20 条，共 250 条');
  await expect(page.getByTestId('prediction-record-row')).toHaveCount(20);
  await expect(page.getByRole('button', { name: '下一页预测明细', exact: true })).toBeEnabled();

  for (const offset of Array.from({ length: 12 }, (_, index) => (index + 1) * 20)) {
    const nextResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === '/api/benchmarks/us20-v1/track-record'
        && url.searchParams.get('offset') === String(offset) && response.status() === 200;
    }, { timeout: 5000 });
    await page.getByRole('button', { name: '下一页预测明细', exact: true }).click();
    await nextResponse;
    await expect(range).toHaveText(`第 ${offset + 1}–${Math.min(offset + 20, 250)} 条，共 250 条`);
  }
  await expect(page.getByTestId('prediction-record-row').filter({ hasText: /猜中|虚惊|漏报|报对了|正确放过/ })).toHaveCount(10);
  await expect(page.getByTestId('prediction-record-row').filter({ hasText: /没猜中|虚惊|漏报/ })).toHaveCount(6);
  await expect(page.getByRole('button', { name: '下一页预测明细', exact: true })).toBeDisabled();
  await page.getByTestId('prediction-record-row').first().getByRole('button').click();
  await expect(page.getByTestId('benchmark-record-detail')).toContainText('较早已结算记录');
  await page.getByTestId('prediction-record-row').first().getByRole('button').click();
  await page.getByRole('button', { name: '上一页预测明细', exact: true }).click();
  await expect(range).toHaveText('第 221–240 条，共 250 条');
  expect(new Set(offsets)).toEqual(new Set(Array.from({ length: 13 }, (_, index) => index * 20)));
});

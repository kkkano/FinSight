import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { makeEmptyTrackRecordFixture, makePendingTrackRecordFixture, makeTrackRecordFixture } from '../src/pages/trackRecord.fixtures';
import type { PredictionTrackRecord } from '../src/types/predictions';

// All API responses in these tests are explicitly labelled, invented UI fixtures.
async function mockLedger(page: Page, getData: () => PredictionTrackRecord, fail?: () => boolean) {
  const headers: Array<Record<string, string>> = [];
  await page.route('**/api/benchmarks/us20-v1/track-record?*', async (route) => {
    headers.push(route.request().headers());
    await route.fulfill({
      status: fail?.() ? 503 : 200,
      contentType: 'application/json',
      body: JSON.stringify(fail?.() ? { detail: 'fixture-internal-error' } : getData()),
    });
  });
  return headers;
}

test('public empty and pending states require no welcome gate and never invent hit rates', async ({ page }) => {
  let fixture = makeEmptyTrackRecordFixture();
  const headers = await mockLedger(page, () => fixture);
  await page.goto('/track-record');
  await expect(page).toHaveURL(/\/track-record$/);
  await expect(page.getByRole('heading', { name: 'US20 预测战绩', exact: true })).toBeVisible();
  await expect(page.getByText('固定采集尚未启用', { exact: true })).toBeVisible();
  await expect(page.getByTestId('direction-results').getByText('等待首批结算', { exact: true })).toBeVisible();
  await expect(page.getByTestId('drawdown-results').getByText('等待首批结算', { exact: true })).toBeVisible();
  await expect(page.getByText('AI 命中率', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '返回 FinSight' })).toHaveAttribute('href', '/welcome');
  expect(await page.evaluate(() => sessionStorage.getItem('finsight-welcome-gate-passed'))).toBeNull();

  fixture = makePendingTrackRecordFixture();
  await page.getByRole('button', { name: '刷新战绩' }).click();
  await expect(page.getByTestId('prediction-coverage').getByText('40 / 40', { exact: true })).toBeVisible();
  await expect(page.getByTestId('prediction-record-row')).toHaveCount(40);
  await expect(page.getByText('AI 命中率', { exact: true })).toHaveCount(0);
  await expect(page.getByTestId('prediction-records-table').getByText('待结算', { exact: true })).toHaveCount(40);
  for (const requestHeaders of headers) {
    expect(requestHeaders.authorization).toBeUndefined();
    expect(requestHeaders['x-finsight-model']).toBeUndefined();
  }
});

test('settled fixtures retain losing groups, unknown models and all failure statuses on desktop and mobile', async ({ page }, testInfo) => {
  const fixture = makeTrackRecordFixture();
  Object.assign(fixture, { endpoint_url: 'https://private-endpoint.fixture', session_id: 'private-session-fixture', raw_reasoning: 'private-raw-thoughts-fixture' });
  await mockLedger(page, () => fixture);
  await page.goto('/track-record');
  await expect(page.getByText('fixture-us20-v1（测试数据，非真实战绩）', { exact: false }).first()).toBeVisible();
  await expect(page.getByTestId('prediction-coverage').getByText('36 / 40', { exact: true })).toBeVisible();
  const direction = page.getByTestId('direction-results');
  await expect(direction.getByText('25.0%', { exact: true })).toBeVisible();
  await expect(direction.getByText('75.0%', { exact: true })).toBeVisible();
  await expect(direction.getByTestId('prediction-baseline-delta').first()).toContainText('-50.0 个百分点');
  await expect(page.getByTestId('direction-unconfirmed-models')).toContainText('模型身份未确认 · 单独统计');
  await expect(page.getByText('已结算 n = 4 · 样本不足', { exact: true })).toBeVisible();
  const risk = page.getByTestId('drawdown-results');
  await expect(risk.getByText('60.0%', { exact: true })).toBeVisible();
  await expect(risk.getByText('80.0%', { exact: true })).toBeVisible();
  await expect(risk).toContainText('实际事件发生率：20.0%（1 / 5）');
  await expect(risk).toContainText('TP · 正确预警');
  await expect(risk).toContainText('FP · 误报');
  await expect(risk).toContainText('TN · 正确排除');
  await expect(risk).toContainText('FN · 漏报');
  const rows = page.getByTestId('prediction-record-row');
  await expect(rows).toHaveCount(40);
  await expect(rows.filter({ hasText: '已结算 · 未命中' })).toHaveCount(6);
  await expect(rows.filter({ hasText: '预测失败' })).toHaveCount(2);
  await expect(rows.filter({ hasText: '等待行情' })).toHaveCount(2);
  await expect(rows.filter({ hasText: '错过登记' })).toHaveCount(1);
  await expect(rows.filter({ hasText: '主动弃权' })).toHaveCount(1);
  await expect(page.locator('body')).not.toContainText('private-endpoint.fixture');
  await expect(page.locator('body')).not.toContainText('private-session-fixture');
  await expect(page.locator('body')).not.toContainText('private-raw-thoughts-fixture');
  await page.screenshot({ path: testInfo.outputPath('track-record-desktop-fixture.png') });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'US20 预测战绩', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('track-record-mobile-fixture.png') });
});

test('a failed public read offers retry without manufacturing an empty result', async ({ page }) => {
  let failing = true;
  await mockLedger(page, makeEmptyTrackRecordFixture, () => failing);
  await page.goto('/track-record');
  await expect(page.getByRole('alert')).toContainText('战绩数据暂时无法读取');
  await expect(page.getByText('已结算 · 成熟样本', { exact: true })).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('fixture-internal-error');
  failing = false;
  await page.getByRole('button', { name: '刷新战绩' }).click();
  await expect(page.getByText('固定采集尚未启用', { exact: true })).toBeVisible();
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
    if (offset === 50 && failNextPage) {
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
  await expect(range).toHaveText('第 1–50 条，共 250 条');
  await expect(page.getByRole('button', { name: '上一页', exact: true })).toBeDisabled();
  await expect(page.getByTestId('prediction-record-row').filter({ hasText: '较早已结算记录' })).toHaveCount(0);
  await expect(page.getByTestId('direction-results').getByText('25.0%', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.getByText('读取失败，仍显示上次成功加载的记录。请重试翻页或刷新。')).toBeVisible();
  await expect(range).toHaveText('第 1–50 条，共 250 条');
  await expect(page.getByTestId('prediction-record-row')).toHaveCount(50);

  for (const offset of [50, 100, 150, 200]) {
    await page.getByRole('button', { name: '下一页', exact: true }).click();
    await expect(range).toHaveText(`第 ${offset + 1}–${offset + 50} 条，共 250 条`);
  }
  await expect(page.getByTestId('prediction-record-row').filter({ hasText: '较早已结算记录' })).toHaveCount(10);
  await expect(page.getByTestId('prediction-record-row').filter({ hasText: '已结算 · 未命中' })).toHaveCount(6);
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '上一页', exact: true }).click();
  await expect(range).toHaveText('第 151–200 条，共 250 条');
  expect(new Set(offsets)).toEqual(new Set([0, 50, 100, 150, 200]));
});

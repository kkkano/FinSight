import { expect, test } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { E2E_SESSION_ID, installAuthenticatedSession } from './helpers/auth';
import type { ResearchArtifact } from '../src/types/runtime';
import type { EvidenceItem } from '../src/types';

const repository = fileURLToPath(new URL('../../', import.meta.url));
const output = join(repository, 'docs/reports/2026-11-07_chat_design_alignment');
mkdirSync(output, { recursive: true });
const cases: Array<{ name: string; run: string; file: string; points: number; series: number; directory?: string; sourceFile?: 'datasets' }> = [
  { name: 'aapl', run: 'chart-live-1-422aa35c1e', file: 'chart_03247108da4cf744.json', points: 251, series: 1 },
  { name: 'nvda-amd', run: 'chart-live-2-c8a888012d', file: 'chart_e77f91d52e0d05f7.json', points: 215, series: 2 },
  { name: 'soxx', run: 'chart-live-3-7a3ce61cd7', file: 'chart_8a38b87d63d3cd14.json', points: 1322, series: 1 },
  { name: 'natural-nvda-amd', run: 'acceptance-natural-9e7eb3eff2-6-retry-34ae', file: 'chart_1f82f920da2e5fc3.json', points: 215, series: 2,
    directory: '.omx/acceptance-natural/acceptance-natural-9e7eb3eff2-6-retry-34ae', sourceFile: 'datasets' },
  { name: 'fresh-aapl-ma20', run: 'acceptance-natural-1f4f06023d-2', file: 'chart_c6c33cc93acfc677.json', points: 24, series: 2,
    directory: '.omx/acceptance-natural/fresh/acceptance-natural-1f4f06023d-2', sourceFile: 'datasets' },
  { name: 'final-nvda-amd', run: 'acceptance-natural-e2e58933cf-6', file: 'chart_a4bfb4bb672a4c16.json', points: 215, series: 2,
    directory: '.omx/acceptance-natural/final-s3/acceptance-natural-e2e58933cf-6', sourceFile: 'datasets' },
];

for (const item of cases) test(`real artifact ${item.name}`, async ({ page }) => {
  const directory = item.directory ? join(repository, item.directory) : join(repository, '.omx/live-charts', item.run);
  const originalPath = join(directory, item.file);
  const path = item.name === 'soxx' && process.env.FINSIGHT_RENDER_SOXX_ARTIFACT || originalPath;
  const bytes = readFileSync(path);
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  const artifact = JSON.parse(bytes.toString('utf8')) as ResearchArtifact;
  const originalArtifact = JSON.parse(readFileSync(originalPath, 'utf8')) as ResearchArtifact;
  // 不读取最终回答正文到页面；仅投影该图实际引用的来源身份/标题/链接/时间。
  const sourceData = JSON.parse(readFileSync(join(directory, item.sourceFile === 'datasets' ? 'datasets.json' : 'terminal.json'), 'utf8'));
  const ledger = (item.sourceFile === 'datasets'
    ? Array.isArray(sourceData.sources) ? sourceData.sources : Object.entries(sourceData.sources).map(([id, value]) => ({ source_id: id, ...value as Record<string, unknown> }))
    : sourceData.evidence_pool) as Array<Record<string, unknown>>;
  const sources: EvidenceItem[] = ledger.filter((source) => artifact.source_refs?.includes(String(source.source_id))).map((source) => ({
    source_id: String(source.source_id), title: typeof source.title === 'string' ? source.title : undefined,
    source: typeof source.source === 'string' ? source.source : typeof source.provider === 'string' ? source.provider : undefined,
    url: typeof source.url === 'string' ? source.url : undefined, as_of: typeof source.as_of === 'string' ? source.as_of : undefined,
  }));
  const suffix = item.name === 'soxx' ? path === originalPath ? '-original' : '-rerender' : '';
  const prefix = `real-chart-${item.name}${suffix}`;
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.addInitScript((sessionId) => {
    localStorage.clear();
    localStorage.setItem('finsight-theme', 'light');
    localStorage.setItem('finsight-session-id', sessionId);
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  }, E2E_SESSION_ID);
  await installAuthenticatedSession(page);
  let executions = 0;
  await page.route('**/api/**', (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.fallback();
    if (pathname === '/api/execute') { executions += 1; return route.abort(); }
    const payload = pathname === '/api/capabilities' ? { ready: true, features: { retrieval: { mode: 'hybrid', full_ready: true } } }
      : pathname === '/api/models' ? { models: [], default_model_id: null }
        : { success: true, items: [], count: 0, profile: {}, data: {}, conversation: { messages: [] } };
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
  });
  await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"healthy"}' }));
  await page.goto('/chat');
  await expect(page.locator('#chat-input')).toBeVisible();
  expect(await page.locator('body').ariaSnapshot()).toContain('textbox');
  await page.evaluate(async ({ artifact, sources }) => {
    const componentPath = '/src/components/chat/ResearchArtifactView.tsx';
    const componentSource = await (await fetch(componentPath)).text();
    const mainSource = await (await fetch('/src/main.tsx')).text();
    const imports = (source: string) => [...source.matchAll(/from\s*["']([^"']+)["']/g)].map((match) => match[1]);
    const reactPath = imports(componentSource).find((path) => /\/react\.js/.test(path));
    const domPath = imports(mainSource).find((path) => /react-dom_client/.test(path));
    if (!reactPath || !domPath) throw new Error('无法定位页面实际使用的 React 模块。');
    const react = await import(reactPath);
    const dom = await import(domPath);
    const { ResearchArtifactView } = await import(componentPath);
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;overflow:auto;background:var(--t-bg);padding:24px;';
    const container = document.createElement('div');
    container.style.cssText = 'max-width:920px;margin:0 auto;';
    overlay.append(container); document.body.append(overlay);
    (window as unknown as { realArtifactInput: unknown }).realArtifactInput = artifact;
    const createRoot = dom.createRoot || dom.default?.createRoot;
    const createElement = react.createElement || react.default?.createElement;
    createRoot(container).render(createElement(ResearchArtifactView, { artifact, sources }));
  }, { artifact, sources });
  const figure = page.getByRole('figure', { name: artifact.title, exact: true });
  await expect(figure.locator('.echarts-for-react').first().locator('canvas, svg').first()).toBeVisible();
  await expect(figure.getByText('1 个数据来源', { exact: true })).toHaveCount(1);
  const sourceFooter = figure.locator(':scope > div').last();
  await expect(sourceFooter).not.toContainText('历史行情数据');
  await expect(sourceFooter).not.toContainText('数据分析结果');
  await expect(sourceFooter).not.toContainText('T00:00:00Z');
  await figure.scrollIntoViewIfNeeded();
  await page.screenshot({ path: join(output, `${prefix}.png`), fullPage: false });

  const rendered = await page.evaluate(async () => {
    const source = await (await fetch('/src/components/charts/EChart.tsx')).text();
    const match = [...source.matchAll(/from\s*["']([^"']+)["']/g)].map((item) => item[1]).find((path) => /\/echarts(?:\.js|\/)/.test(path));
    if (!match) throw new Error('无法定位当前渲染器使用的 ECharts 模块。');
    const echarts = await import(match);
    return [...document.querySelectorAll('.research-artifact .echarts-for-react')].map((element, index) => {
      const instance = echarts.getInstanceByDom(element);
      if (!instance) throw new Error('图表实例尚未就绪。');
      if (index === 0) (window as unknown as { realChartInstance: unknown }).realChartInstance = instance;
      const option = instance.getOption();
      const areas = option.series[0]?.markArea?.data ?? [];
      return { labels: option.xAxis[0].data, unit: option.yAxis[0].name, axisType: option.yAxis[0].type, series: option.series.map((series: { name: string; data: number[] }) => ({ name: series.name, data: series.data })),
        areas: areas.map((area: Array<{ xAxis: string; name?: string; tooltip?: { formatter: string } }>) => ({ name: area[0].name, tooltip: area[0].tooltip?.formatter, start: area[0].xAxis, end: area[1].xAxis,
          startPixel: instance.convertToPixel({ xAxisIndex: 0 }, area[0].xAxis), endPixel: instance.convertToPixel({ xAxisIndex: 0 }, area[1].xAxis) })) };
    });
  });
  const rows = artifact.data!.rows!;
  expect(rows).toEqual(originalArtifact.data!.rows);
  expect(rendered[0].labels).toHaveLength(item.points);
  expect(rendered[0].series).toHaveLength(item.series);
  for (let index = 0; index < item.series; index += 1) {
    const series = artifact.spec!.series![index];
    expect(rendered[0].series[index].data).toEqual(rows.map((row) => row[series.field]));
  }
  if (item.name.endsWith('nvda-amd')) {
    expect(rendered[0].unit).toBe('%');
    expect(rendered[0].series[1].data.at(-1)).toBe(109.67501354127754);
  }
  let comparisonCheck: Record<string, unknown> | undefined;
  if (item.name === 'final-nvda-amd') {
    let prior: number | undefined;
    const dates: string[] = [];
    for (const row of rows) {
      const sign = Math.sign(Number(row.series_1) - Number(row.series_2));
      if (!sign) continue;
      if (prior !== undefined && sign !== prior) dates.push(String(row.date));
      prior = sign;
    }
    expect(dates).toEqual(['2026-01-06', '2026-01-13', '2026-02-05', '2026-03-19']);
    const stats = sourceData.records[artifact.dataset_refs![0]].output.comparison_stats;
    expect(stats.crossovers).toEqual([{ left: 'NVDA', right: 'AMD', count: 4, dates, dates_truncated: false }]);
    comparisonCheck = { crossovers: stats.crossovers, lead_days: stats.lead_days,
      independent_crossover_dates: dates, strictly_increasing: stats.strictly_increasing };
  }
  let meanCheck: Record<string, unknown> | undefined;
  if (item.name === 'fresh-aapl-ma20') {
    const ref = (artifact.method?.input_refs as string[])[0];
    const history = sourceData.records[ref].output.data as Array<{ time: string; close: number }>;
    expect(history).toHaveLength(65);
    expect(rendered[0].unit).toBe('USD');
    const coverage = (artifact as ResearchArtifact & { coverage: Record<string, Record<string, unknown>> }).coverage;
    for (const field of ['close', 'ma20']) expect(coverage[field]).toMatchObject({ points: 24, valid: 24, missing: 0, leading_missing: 0,
      first_valid: '2026-10-06', last_valid: '2026-11-06' });
    const comparisons = rows.map((row) => {
      const index = history.findIndex((source) => source.time === row.time);
      expect(index).toBeGreaterThanOrEqual(19);
      const expected = history.slice(index - 19, index + 1).reduce((sum, source) => sum + source.close, 0) / 20;
      // 原产物明确round(v, 2)；保留其两位值，只按该声明精度核对独立均值。
      expect(Math.abs(Number(row.close) - history[index].close)).toBeLessThanOrEqual(.005000001);
      expect(Math.abs(Number(row.ma20) - expected)).toBeLessThanOrEqual(.005000001);
      return { date: row.time, rendered: row.ma20, source_mean: expected };
    });
    expect(rendered[0].series.every((series: { data: number[] }) => series.data.every(Number.isFinite))).toBe(true);
    meanCheck = { source_rows: history.length, source_window: 20, declared_chart_decimal_places: 2, comparisons,
      full_precision_last_mean: comparisons.at(-1)!.source_mean, chart_last_ma20: rows.at(-1)!.ma20, coverage };
  }
  const panelBoundaries = (artifact.data?.panels ?? []).map((panel, index) => {
    const annotation = artifact.spec!.annotations![index];
    const x = artifact.spec!.x!;
    const expectedStart = String(annotation.start).slice(0, 10);
    const expectedEnd = String(annotation.end).slice(0, 10);
    const inWindow = rows.filter((row) => String(row[x]).slice(0, 10) >= expectedStart && String(row[x]).slice(0, 10) <= expectedEnd);
    const firstIndex = rows.findIndex((row) => String(row[x]).slice(0, 10) === expectedStart);
    return { title: panel.title, source_rows: panel.rows.length, expected_declining_periods: inWindow.length,
      baseline_included: panel.baseline_included === true, source_first: String(panel.rows[0]?.[x]), source_last: String(panel.rows.at(-1)?.[x]),
      expected_baseline: firstIndex > 0 ? rows[firstIndex - 1] : null,
      expected_end: expectedEnd, end_included: String(panel.rows.at(-1)?.[x]).slice(0, 10) === expectedEnd };
  });
  if (item.name === 'soxx') {
    expect(rendered[0].areas).toHaveLength(9);
    expect(rendered).toHaveLength(7);
    expect(rendered[0].axisType).toBe('log');
    expect(rendered[0].areas.map((area: { name: string }) => area.name)).toEqual(Array.from({ length: 9 }, (_, index) => `区间${index + 1}`));
    for (const area of rendered[0].areas) {
      expect(rendered[0].labels).toContain(area.start);
      expect(rendered[0].labels).toContain(area.end);
      expect(Number.isFinite(area.startPixel) && Number.isFinite(area.endPixel)).toBe(true);
      expect(area.endPixel).toBeGreaterThan(area.startPixel);
    }
    const chartBounds = (await figure.locator('.echarts-for-react').first().boundingBox())!;
    const lastArea = rendered[0].areas.at(-1)!;
    await page.mouse.move(chartBounds.x + (lastArea.startPixel + lastArea.endPixel) / 2, chartBounds.y + 80);
    await expect.poll(() => page.evaluate(() => {
      const instance = (window as unknown as { realChartInstance: { getZr: () => { storage: { getDisplayList: () => Array<{ style?: { text?: string } }> } } } }).realChartInstance;
      return instance.getZr().storage.getDisplayList().map((element) => element.style?.text || '').join('\n');
    })).toContain('5周 -30.4% 进行中');
    await page.screenshot({ path: join(output, `${prefix}-tooltip.png`), fullPage: false });
    await page.mouse.move(1400, 920);
    artifact.data!.panels!.forEach((panel, index) => {
      expect(rendered[index + 1].series[0].data).toEqual(panel.rows.map((row) => row.close));
      expect(rendered[index + 1].labels).toEqual(panel.rows.map((row) => row.date));
      expect(rendered[index + 1].axisType).toBe('value');
      if (panel.baseline_included) {
        expect(panelBoundaries[index].end_included).toBe(true);
        expect(panel.rows).toHaveLength(panelBoundaries[index].expected_declining_periods + 1);
        expect(panel.rows[0]).toEqual(panelBoundaries[index].expected_baseline);
        expect(panel.periods).toBe(panelBoundaries[index].expected_declining_periods);
      }
    });
    const intervalList = figure.locator('details').filter({ hasText: '编号对应主图' });
    await intervalList.locator('summary').click();
    await expect(intervalList.locator('li')).toHaveCount(9);
    await expect(figure.getByText('各区间独立纵轴，展示各自的实际价格。', { exact: true })).toBeVisible();
    await intervalList.locator('summary').click();
  }
  await figure.getByText('查看代码和数据', { exact: true }).click();
  await figure.getByRole('button', { name: '数据', exact: true }).click();
  const visibleData = await figure.innerText();
  expect(visibleData).not.toMatch(/twelve_data|market_chart|get_stock|as_of|price_basis|dividends_included|series_[12]|consecutive_decline_streaks/);
  if (item.name.endsWith('nvda-amd')) {
    expect(visibleData).toContain('NVDA（%）');
    expect(visibleData).toContain('AMD（%）');
    expect(visibleData).toContain('价格口径');
    expect(visibleData).toContain('未注明');
  }
  await page.screenshot({ path: join(output, `${prefix}-data.png`), fullPage: false });
  const stored = await page.evaluate(() => (window as unknown as { realArtifactInput: unknown }).realArtifactInput);
  expect(stored).toEqual(artifact);
  expect(createHash('sha256').update(readFileSync(path)).digest('hex')).toBe(sha256);
  expect(executions).toBe(0);
  writeFileSync(join(output, `${prefix}.json`), JSON.stringify({ evidence_kind: 'existing_model_artifact_rendering', source_file: path, sha256, run_id: item.run,
    source_ids: sources.map((source) => source.source_id), source_proof: sources, point_count: rows.length,
    series: rendered[0].series.map((series: { name: string; data: number[] }) => ({ name: series.name, first: series.data[0], last: series.data.at(-1), points: series.data.length })),
    unit: rendered[0].unit, source_values_unchanged: true, model_calls: executions, mean_check: meanCheck, comparison_check: comparisonCheck, annotations: rendered[0].areas,
    panel_boundaries: panelBoundaries, visible_metadata: visibleData.slice(-6000) }, null, 2), 'utf8');
});

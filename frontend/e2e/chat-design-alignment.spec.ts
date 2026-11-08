import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { E2E_SESSION_ID, installAuthenticatedSession } from './helpers/auth';
import { renderDesignReference } from './helpers/designReference';

const output = fileURLToPath(new URL('../../docs/reports/2026-11-07_chat_design_alignment/', import.meta.url));
mkdirSync(output, { recursive: true });
const bars = Array.from({ length: 260 }, (_, index) => ({ time: new Date(Date.UTC(2026, 10, 6) - (259 - index) * 86400000).toISOString().slice(0, 10),
  open: 150 + index * .18, close: 151 + index * .18 + Math.sin(index / 6) * 3,
  high: 155 + index * .18, low: 147 + index * .18, volume: 20000000 + (index % 9) * 1200000 }));

async function prepare(page: Page, dark: boolean) {
  const controls = { marketFailure: false };
  await page.addInitScript(({ sessionId, dark }) => {
    localStorage.clear();
    localStorage.setItem('finsight-theme', dark ? 'dark' : 'light');
    localStorage.setItem('finsight-session-id', sessionId);
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (!url.endsWith('/api/execute') || init?.method !== 'POST') return originalFetch(input, init);
      const request = JSON.parse(String(init.body));
      const source = { source_id: 'Sabc123', title: 'AAPL 财务与行情核查资料', source: 'yfinance', url: 'https://example.com/evidence', as_of: '2026-11-06' };
      const reasoning = '先核对本轮实际取得的价格、盈利质量和资料时点，再区分事实与尚未验证的假设。\n'.repeat(18);
      const intro = '我会先核对近期价格，再看支撑与盈利质量。\n\n';
      const answer = '现有资料支持分批观察，暂不追高。\n\n参考资料列出了价格与财务口径[Sabc123]。\n\n支撑位为 185 美元，需要结合后续财报重新评估。';
      const artifact = { artifact_id: 'design-chart', kind: 'chart', title: 'AAPL 历史价格与观察区间', source_refs: ['Sabc123'],
        spec: { chart_type: 'line', x: 'date', series: [{ field: 'close', name: '收盘价', unit: 'USD' }] },
        data: { rows: Array.from({ length: 30 }, (_, index) => ({ date: `2026-10-${String(index + 1).padStart(2, '0')}`, close: 175 + index * .6 + Math.sin(index / 3) * 2 })) },
        method: { description: '布局验收固定数据；此图不用于金融结论。', as_of: '2026-11-06' } };
      const encoder = new TextEncoder();
      let seq = 0;
      const stream = new ReadableStream({ start(controller) {
        const emit = (event: Record<string, unknown>) => controller.enqueue(encoder.encode('data: ' + JSON.stringify({ schema_version: 2,
          run_id: request.run_id, session_id: request.session_id, seq: ++seq, ...event }) + '\n\n'));
        emit({ type: 'reasoning.delta', payload: { block_id: 'root_reasoning_1', kind: 'provider_raw', delta: reasoning, agent_id: 'root', agent_label: '主研究员' } });
        setTimeout(() => {
          emit({ type: 'content.delta', payload: { block_id: 'intro', delta: intro } });
          emit({ type: 'tool.started', payload: { tool_call_id: 'quote', name: 'get_stock_price', inputs: { ticker: 'AAPL' }, display: { target: 'AAPL', result: '' } } });
          emit({ type: 'tool.result', payload: { tool_call_id: 'quote', name: 'get_stock_price', duration_ms: 420,
            display: { target: 'AAPL', result: '197.62 USD · 收盘价' }, output_preview: { price: 197.62, currency: 'USD' }, sources: [source] } });
          emit({ type: 'content.delta', payload: { block_id: 'answer', delta: answer } });
          emit({ type: 'artifact.ready', payload: { artifact } });
          emit({ type: 'done', response: intro + answer, run_status: 'completed', success: true, persistence_status: 'ephemeral',
            evidence_pool: [source], price_levels: [{ price: 185, label: '支撑', source_block_id: 'answer', ticker: 'AAPL' }],
            blocks: [
              { id: 'root_reasoning_1', kind: 'reasoning', reasoning_kind: 'provider_raw', content: reasoning, revision: 0, seq: 1, duration_ms: 1500, agent_label: '主研究员' },
              { id: 'intro', kind: 'text', content: intro, revision: 0, seq: 2 },
              { id: 'answer', kind: 'text', content: answer, revision: 0, seq: 5 },
              { id: 'design-chart', kind: 'artifact', artifact, revision: 0, seq: 6 },
            ] });
          controller.close();
        }, 1800);
      } });
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream', 'X-Run-Id': request.run_id } });
    };
  }, { sessionId: E2E_SESSION_ID, dark });
  await installAuthenticatedSession(page);
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.fallback();
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/api/capabilities') return json({ ready: true, features: { retrieval: { mode: 'hybrid', full_ready: true } } });
    if (path === '/api/models') return json({ models: [{ id: 'system:server-default', model: 'test-model', label: '验收模型', provider: 'system', available: true, native_tool_calls: true, effort_options: [] }], default_model_id: 'system:server-default' });
    if (path.startsWith('/api/stock/company/')) return json({ ticker: 'AAPL', status: 'ok', name: 'Apple Inc.', name_zh: '苹果', exchange: 'NMS', source: 'yfinance', as_of: '2026-11-06' });
    if (path.startsWith('/api/stock/kline/')) return controls.marketFailure ? json({ detail: '行情服务暂不可用' }, 503)
      : json({ data: { kline_data: bars, source: 'yfinance', currency: 'USD', as_of: '2026-11-06', data_kind: 'daily_close' } });
    if (path.startsWith('/api/stock/price/')) return json({ data: { data: { price: 197.62, change: -1.32, change_percent: -.66 }, source: 'yfinance', currency: 'USD', as_of: '2026-11-06', data_kind: 'daily_close' } });
    if (path === '/api/dashboard') return json({ state: { active_asset: { symbol: 'AAPL', display_name: '苹果', type: 'equity' }, capabilities: {} },
      data: { snapshot: {}, charts: {}, news: { market: [], impact: [] }, valuation: { market_cap: 2900000000000, trailing_pe: 28.4, dividend_yield: .0052 } } });
    return json({ success: true, session_id: E2E_SESSION_ID, items: [], count: 0, watchlist: [], profile: {}, conversation: { messages: [] } });
  });
  await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"healthy"}' }));
  await page.goto('/chat');
  await expect(page.locator('#chat-input')).toBeVisible();
  expect(await page.locator('body').ariaSnapshot()).toContain('textbox');
  return controls;
}

for (const dark of [false, true]) for (const narrow of [false, true]) {
  test(`chat design ${dark ? 'dark' : 'light'} ${narrow ? 'narrow' : 'wide'}`, async ({ page }) => {
    const suffix = `${dark ? 'dark' : 'light'}-${narrow ? 'narrow' : 'wide'}`;
    await page.setViewportSize({ width: narrow ? 390 : 1440, height: 960 });
    const controls = await prepare(page, dark);
    await expect(page.getByTestId('sidebar')).toHaveCSS('width', narrow ? '56px' : '240px');
    const screenshot = async (name: string) => {
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: join(output, `${name}-${suffix}.png`), fullPage: false });
    };
    await page.getByTestId('context-panel-expand').click();
    await expect(page.getByTestId('context-panel')).toContainText('聊到股票时');
    await screenshot('panel-empty');
    await page.getByRole('button', { name: '收起面板', exact: true }).click();
    await page.locator('#chat-input').fill('分析 AAPL 的价格与盈利质量，并画图');
    await page.getByTestId('chat-send-btn').click();
    await expect(page.getByTestId('reasoning-content')).toBeVisible();
    expect((await page.getByTestId('reasoning-content').boundingBox())!.height).toBeLessThanOrEqual(160);
    await screenshot('streaming');
    await expect(page.getByText('现有资料支持分批观察，暂不追高。', { exact: true })).toBeVisible();
    await expect(page.getByTestId('chat-stop-btn')).toHaveCount(0);
    await expect(page.getByTestId('reasoning-content')).toHaveCount(0);
    await page.locator('#chat-scroll-container').evaluate((node) => { node.scrollTop = 0; });
    await screenshot('main');
    await page.getByRole('button', { name: /已处理.*1 次工具调用/ }).click();
    const intro = page.getByText('我会先核对近期价格，再看支撑与盈利质量。', { exact: true });
    const tool = page.locator('.tool-activity-row').filter({ hasText: '获取行情' });
    expect(await intro.evaluate((node, other) => Boolean(node.compareDocumentPosition(other as Node) & Node.DOCUMENT_POSITION_FOLLOWING), await tool.elementHandle())).toBe(true);
    await tool.click();
    await expect(page.getByText('参数', { exact: true })).toBeVisible();
    await screenshot('main-expanded');
    await page.getByRole('figure', { name: 'AAPL 历史价格与观察区间' }).scrollIntoViewIfNeeded();
    await screenshot('chat-chart');
    await page.getByLabel('查看引用 1').click();
    const panel = page.getByTestId('context-panel');
    await expect(panel.getByText('Yahoo Finance', { exact: false }).first()).toBeVisible();
    await expect(panel.locator('[data-source-id="Sabc123"]')).toBeVisible();
    await expect(panel.locator('[data-source-id="Sabc123"]')).toHaveClass(/highlight/);
    await expect(panel.getByTestId('context-chart-surface')).toHaveCSS('height', '236px');
    await expect(panel.getByText('对话中提到的价位', { exact: true })).toBeVisible();
    await screenshot('right-panel');
    await page.getByRole('button', { name: '收起面板', exact: true }).click();
    controls.marketFailure = true;
    await page.getByTestId('context-panel-expand').click();
    await expect(page.getByRole('button', { name: '重试行情' })).toBeVisible();
    await screenshot('panel-failure');
    await page.getByRole('button', { name: '收起面板', exact: true }).click();
    await page.getByTestId('sidebar-nav-history').click();
    await expect(page.getByLabel('搜索对话')).toBeVisible();
    await expect(page.getByTestId('history-conversation')).toHaveCount(1);
    await screenshot('history');
    await page.getByTestId('history-conversation').hover();
    await page.getByTestId('history-conversation').getByRole('button', { name: /删除对话/ }).click();
    await expect(page.getByRole('dialog', { name: '删除对话确认' })).toBeVisible();
    await screenshot('history-delete-confirm');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('history-conversation')).toHaveCount(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    const original = await page.context().newPage();
    await original.setViewportSize({ width: narrow ? 390 : 1440, height: 960 });
    for (const name of ['Main', 'Streaming', 'ChatChart', 'RightPanel']) {
      await renderDesignReference(original, name, dark);
      await expect(original.locator('.fs')).toBeVisible();
      await original.screenshot({ path: join(output, `reference-${name.toLowerCase()}-${suffix}.png`), fullPage: false });
    }
    await original.close();
  });
}

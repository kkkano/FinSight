import { expect, test, type Page } from '@playwright/test';
import { E2E_SESSION_ID, installAuthenticatedSession } from './helpers/auth';

async function prepare(page: Page, dark: boolean) {
  await page.addInitScript(({ dark, session }) => {
    localStorage.clear();
    localStorage.setItem('finsight-theme', dark ? 'dark' : 'light');
    localStorage.setItem('finsight-session-id', session);
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  }, { dark, session: E2E_SESSION_ID });
  await installAuthenticatedSession(page);
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.fallback();
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (pathname === '/api/models') return json({ models: [], default_model_id: null });
    if (pathname === '/api/capabilities') return json({ ready: true, features: {} });
    if (pathname === '/api/dashboard') return json({ state: { active_asset: { symbol: 'AAPL', display_name: 'Apple', type: 'equity' }, capabilities: {} },
      data: { snapshot: {}, charts: {}, news: { market: [], impact: [] }, valuation: {} } });
    if (pathname.startsWith('/api/stock/company/')) return json({ ticker: 'AAPL', status: 'ok', name: 'Apple Inc.', source: 'yfinance' });
    if (pathname.startsWith('/api/stock/price/')) return json({ data: { data: { price: 100, currency: 'USD' }, source: 'yfinance', as_of: '2026-11-06' } });
    if (pathname.startsWith('/api/stock/kline/')) return json({ data: { kline_data: [], source: 'yfinance' } });
    return json({ success: true, session_id: E2E_SESSION_ID, items: [], watchlist: [], profile: {}, count: 0, conversation: { messages: [] } });
  });
  await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"healthy"}' }));
  await page.goto('/chat');
  await expect(page.locator('#chat-input')).toBeVisible();
  await page.evaluate(async () => {
    const path = '/src/store/useStore.ts';
    const { useStore } = await import(/* @vite-ignore */ path);
    const source = { source_id: 'Sabc123', title: 'get_technical_snapshot output', source: 'get_technical_snapshot',
      source_name: 'yfinance', as_of: '2026-11-06', currency: 'USD', price_basis: 'split_adjusted_close',
      dividends_included: false, meta: { parameters: { rsi_period: 14, ma_periods: [20, 50, 200] } } };
    useStore.setState({ currentTicker: 'AAPL', showRightPanel: false, messages: [
      { id: 'source-user', role: 'user', content: '核对 AAPL 的技术指标与最新消息', timestamp: Date.now() - 2 },
      { id: 'source-answer', role: 'assistant', runId: 'source-run', content: '技术指标已取得，参考本轮数据[数据集 1fcdf70c3d755a3fd3，来源 Sabc123]。',
        timestamp: Date.now() - 1, evidence_pool: [source, { source_id: 'Sdef456', title: '公司经营更新（界面测试样本）',
          source: 'company_ir', url: 'https://example.com/investor-update', as_of: '2026-11-06' }], runStatus: 'completed' },
    ] });
  });
  await page.getByTestId('answer-sources').locator('summary').first().click();
  for (const group of await page.getByTestId('source-group').all()) await group.locator('summary').first().click();
}

for (const dark of [false, true]) {
  test(`source details and original article ${dark ? 'dark' : 'light'}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    await prepare(page, dark);
    expect(await page.locator('body').ariaSnapshot()).toContain('查看来源 1 详情');
    const original = page.locator('#chat-scroll-container').getByRole('link', { name: /公司经营更新/ });
    await expect(original).toHaveAttribute('href', 'https://example.com/investor-update');
    await expect(original).toHaveAttribute('target', '_blank');
    await page.getByRole('button', { name: '查看来源 1 详情' }).click();
    const details = page.locator('#chat-scroll-container').getByTestId('source-details');
    await expect(details).toContainText('Yahoo Finance');
    await expect(details).toContainText('2026-11-06');
    await expect(details).toContainText('RSI 周期14');
    await expect(details).toContainText('均线周期20、50、200');
    await expect(details).toContainText('拆股调整收盘价');
    await expect(details).toContainText('这份数据没有单独的原文链接。');
    await page.getByLabel('查看引用 1').click();
    const panel = page.getByTestId('context-panel');
    await expect(panel.getByTestId('source-details')).toBeVisible();
    await expect(panel.getByTestId('source-details')).toContainText('Yahoo Finance');
    await expect(page.locator('body')).not.toContainText('dataset_');
    await expect(page.locator('body')).not.toContainText('get_technical_snapshot');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`sources-${dark ? 'dark' : 'light'}.png`), animations: 'disabled' });
    await page.evaluate(async () => {
      const path = '/src/store/useStore.ts';
      const { useStore } = await import(/* @vite-ignore */ path);
      const messages = useStore.getState().messages.map((message) => message.evidence_pool ? { ...message,
        evidence_pool: message.evidence_pool.map((source, index) => index === 0 ? { ...source, url: 'https://finance.yahoo.com/quote/AAPL/history/' } : source),
      } : message);
      useStore.setState({ messages });
    });
    await expect(panel.getByRole('link', { name: '打开原始资料' })).toHaveAttribute('href', 'https://finance.yahoo.com/quote/AAPL/history/');
    await page.getByRole('button', { name: '收起面板', exact: true }).click();
    await page.evaluate(async () => {
      const path = '/src/store/useStore.ts';
      const { useStore } = await import(/* @vite-ignore */ path);
      useStore.setState({ currentTicker: null, messages: [
        { id: 'macro-user', role: 'user', content: '核对美国宏观利率', timestamp: Date.now() - 2 },
        { id: 'macro-answer', role: 'assistant', runId: 'macro-run', content: '宏观数据已取得[S998abc]。', timestamp: Date.now() - 1,
          evidence_pool: [{ source_id: 'S998abc', title: '美国利率资料（界面测试样本）', source: 'fred', as_of: '2026-11-06' }] },
      ] });
    });
    await page.getByLabel('查看引用 1').click();
    await expect(panel.getByTestId('source-details')).toContainText('美联储 FRED');
    await expect(panel).not.toContainText('聊到股票时');
  });
}

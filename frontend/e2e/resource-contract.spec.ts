import { expect, test, type Page, type Route } from '@playwright/test';

import { installAuthenticatedSession } from './helpers/auth';

const json = (route: Route, payload: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) });

async function setup(page: Page) {
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem('finsight-theme', 'light');
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  });
  await installAuthenticatedSession(page);
  await page.route('**/health', (route) => json(route, { status: 'healthy' }));
  await page.route('**://*/api/**', (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return route.fallback();
    if (url.pathname === '/api/capabilities') return json(route, { status: 'ready', ready: true,
      features: { retrieval: { mode: 'hybrid', full_ready: true } } });
    if (url.pathname === '/api/dashboard') {
      const symbol = url.searchParams.get('symbol') || 'AAPL';
      return json(route, { success: true, state: { active_asset: { symbol, type: 'equity', display_name: symbol }, capabilities: { market_chart: true } },
        data: { snapshot: { currency: 'USD' }, charts: {}, news: {}, meta: {} } });
    }
    if (url.pathname.startsWith('/api/stock/price/')) return json(route, { ticker: 'AAPL', data: {
      data: { price: 100, change: 0, change_percent: 0, currency: 'USD' }, quality: 'trusted', provider: 'fixture', as_of: new Date().toISOString(),
    } });
    if (url.pathname === '/api/predictions/eligibility') return json(route, { eligible: false, available: false });
    return json(route, { items: [], count: 0, profile: {}, messages: [], data: {}, stats: null });
  });
}

test('Today and Dashboard share watchlist mutations without restoring an old page cache', async ({ page }) => {
  await setup(page);
  let items: Array<{ ticker: string; note: string; added_at: string }> = [];
  await page.route('**/api/watchlist**', (route) => {
    const method = route.request().method();
    if (method === 'POST') {
      const { ticker } = route.request().postDataJSON();
      const item = { ticker, note: '', added_at: new Date().toISOString() };
      items = [...items, item];
      return json(route, { item });
    }
    if (method === 'DELETE') {
      const ticker = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1) || '');
      items = items.filter((item) => item.ticker !== ticker);
      return json(route, {});
    }
    return json(route, { items });
  });
  await page.goto('/today');
  await expect(page.getByTestId('today-watchlist-empty')).toBeVisible();
  await page.getByTestId('sidebar-nav-dashboard').click();
  await page.getByRole('button', { name: '添加自选', exact: true }).click();
  await page.getByRole('textbox', { name: '输入股票代码' }).fill('MSFT');
  await page.getByRole('button', { name: '确认添加', exact: true }).click();
  await expect(page.getByRole('button', { name: '从自选列表中删除 MSFT' })).toBeVisible();
  await page.getByTestId('sidebar-nav-today').click();
  await expect(page.getByTestId('today-watchlist-card')).toContainText('MSFT');
  await page.getByTestId('sidebar-nav-dashboard').click();
  await page.getByRole('button', { name: '从自选列表中删除 MSFT' }).click();
  await page.getByTestId('sidebar-nav-today').click();
  await expect(page.getByTestId('today-watchlist-empty')).toBeVisible();
  expect(items).toEqual([]);
});

test('account report directory includes both sessions and retries the failed selected detail', async ({ page }, testInfo) => {
  await setup(page);
  const indexRequests: URL[] = [];
  let detailReads = 0;
  await page.route('**/api/reports/index**', (route) => {
    indexRequests.push(new URL(route.request().url()));
    return json(route, { count: 2, items: [
      { report_id: 'first', session_id: 'session-1', title: '第一会话报告', ticker: 'AAPL' },
      { report_id: 'second', session_id: 'session-2', title: '第二会话报告', ticker: 'MSFT' },
    ] });
  });
  await page.route('**/api/reports/replay/*', (route) => {
    const reportId = new URL(route.request().url()).pathname.split('/').at(-1)!;
    if (reportId === 'second' && ++detailReads === 1) return json(route, { detail: '报告详情临时失败' }, 503);
    return json(route, { report: { report_id: reportId, ticker: 'MSFT', company_name: 'Microsoft', title: '跨会话详情',
      summary: '正文已恢复', sentiment: 'neutral', confidence_score: null, generated_at: '2026-10-08T00:00:00Z', sections: [], citations: [] } });
  });
  await page.goto('/history?report=second');
  await expect(page.getByTestId('report-history-item')).toHaveCount(2);
  await expect(page.getByRole('alert')).toContainText('报告详情临时失败');
  const listReads = indexRequests.length;
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.getByText('总体结论：正文已恢复', { exact: true })).toBeVisible();
  expect(detailReads).toBe(2);
  expect(indexRequests.length).toBe(listReads);
  expect(indexRequests.every((url) => !url.searchParams.has('session_id'))).toBe(true);
  await page.getByLabel('报告会话筛选').selectOption('session-2');
  await expect(page.getByTestId('report-history-item')).toHaveCount(1);
  await expect(page.getByTestId('report-history-item')).toContainText('第二会话报告');
  await page.screenshot({ path: testInfo.outputPath('report-history-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('sidebar')).toHaveCSS('width', '56px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('report-history-mobile.png') });
});

test('lexical retrieval is visible despite successful core health', async ({ page }) => {
  await setup(page);
  await page.route('**/api/capabilities', (route) => json(route, { status: 'ready', ready: true,
    features: { retrieval: { mode: 'lexical', full_ready: false } } }));
  await page.goto('/today');
  await expect(page.getByTestId('workspace-health-banner')).toContainText('当前使用词法检索');
});

test('new route owns the subject while dashboard data is pending or unavailable', async ({ page }) => {
  await setup(page);
  await page.goto('/dashboard/AAPL');
  await expect(page.getByRole('main')).toContainText('AAPL');
  await page.route('**/api/dashboard?symbol=NVDA', async route => {
    await new Promise(resolve => setTimeout(resolve, 1000));
    await json(route, { detail: '本次来源不可用' }, 503);
  });
  await page.goto('/dashboard/NVDA');
  await expect(page.getByRole('main')).toContainText('NVDA');
  await expect(page.getByRole('region', { name: 'NVDA AI 动态' })).toBeVisible();
  await expect(page.getByRole('main')).not.toContainText('Apple');
  await page.getByRole('button', { name: '追问', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '输入聊天消息' })).toHaveValue(/NVDA/);
});

test('command palette starts a new session instead of retaining the previous context', async ({ page }) => {
  await setup(page);
  await page.goto('/chat');
  const previous = await page.evaluate(() => localStorage.getItem('finsight-session-id'));
  await page.getByTestId('sidebar-nav-command-palette').click();
  await page.getByRole('option', { name: '新建对话', exact: true }).click();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('finsight-session-id'))).not.toBe(previous);
});

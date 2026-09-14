import { expect, test, type Page, type Route } from '@playwright/test';

import { installAuthenticatedSession } from './helpers/auth';

const fulfillJson = (route: Route, payload: unknown, status = 200) => route.fulfill({
  status,
  contentType: 'application/json',
  body: JSON.stringify(payload),
});

const installCommonRoutes = async (page: Page) => {
  await page.route('**/health', (route) => fulfillJson(route, { status: 'healthy' }));
  await page.route('**/api/user/profile**', (route) => fulfillJson(route, { profile: {} }));
  await page.route('**/api/reports/index**', (route) => fulfillJson(route, { count: 0, items: [] }));
};

test('root redirects anonymous visitors to Today without reading personal APIs', async ({ page }) => {
  const personalRequests: string[] = [];
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  });
  await page.route('**/api/watchlist**', (route) => {
    personalRequests.push(route.request().url());
    return fulfillJson(route, { items: [] });
  });
  await page.route('**/api/predictions/**', (route) => {
    personalRequests.push(route.request().url());
    return fulfillJson(route, { items: [], stats: null });
  });

  await page.goto('/');

  await expect(page).toHaveURL(/\/today$/);
  await expect(page.getByRole('heading', { name: '登录后查看你的今日摘要' })).toBeVisible();
  expect(personalRequests).toEqual([]);
});

test('root symbol query redirects to the matching dashboard', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  });
  await installCommonRoutes(page);
  await page.route('**/api/dashboard**', (route) => fulfillJson(route, { ticker: 'AAPL', data: {} }));

  await page.goto('/?symbol=AAPL');

  await expect(page).toHaveURL(/\/dashboard\/AAPL\?symbol=AAPL$/);
});

test('authenticated Today shows empty watchlist and prediction states', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  });
  await installAuthenticatedSession(page);
  await installCommonRoutes(page);
  await page.route('**/api/watchlist**', (route) => fulfillJson(route, { items: [] }));
  await page.route('**/api/predictions/history**', (route) => fulfillJson(route, { items: [] }));
  await page.route('**/api/predictions/stats**', (route) => fulfillJson(route, {
    stats: { predictions: 0, resolved: 0, hit_rate: null },
  }));

  await page.goto('/today');

  await expect(page.getByTestId('today-watchlist-empty')).toBeVisible();
  await expect(page.getByTestId('today-predictions-empty')).toBeVisible();
  await expect(page.getByTestId('today-followups-empty')).toBeVisible();
});

test('authenticated Today exposes quote and prediction failures with retry actions', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  });
  await installAuthenticatedSession(page);
  await installCommonRoutes(page);
  await page.route('**/api/watchlist**', (route) => fulfillJson(route, {
    items: [{ ticker: 'AAPL', note: 'Apple', added_at: '2026-09-15T00:00:00Z' }],
  }));
  await page.route('**/api/stock/price/**', (route) => route.fulfill({ status: 503, body: 'unavailable' }));
  await page.route('**/api/predictions/history**', (route) => fulfillJson(route, {
    error: { code: 'prediction_store_unavailable', message: '研究假设暂时不可用' },
  }, 503));
  await page.route('**/api/predictions/stats**', (route) => fulfillJson(route, { stats: null }));

  await page.goto('/today');

  await expect(page.getByTestId('today-quotes-error')).toBeVisible();
  await expect(page.getByTestId('today-predictions-error')).toBeVisible();
  await expect(page.getByTestId('today-quotes-error').getByRole('button', { name: '重试' })).toBeVisible();
  await expect(page.getByTestId('today-predictions-error').getByRole('button', { name: '重试' })).toBeVisible();
});

test('authenticated Today renders sourced data and navigates from cards', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  });
  await installAuthenticatedSession(page);
  await installCommonRoutes(page);
  await page.route('**/api/watchlist**', (route) => fulfillJson(route, {
    items: [{ ticker: 'AAPL', note: 'Apple', added_at: '2026-09-15T00:00:00Z' }],
  }));
  await page.route('**/api/stock/price/**', (route) => fulfillJson(route, {
    ticker: 'AAPL',
    data: {
      data: { price: 233.42, change: 2.5, change_percent: 1.08 },
      provider: 'finnhub',
      source: 'quote',
      as_of: '2026-09-15T01:30:00Z',
      freshness_seconds: 10,
      quality: 'trusted',
      degraded: false,
      error_code: null,
      attempted_providers: ['finnhub'],
      cached: false,
    },
    cached: false,
  }));
  await page.route('**/api/predictions/history**', (route) => fulfillJson(route, {
    items: [{
      prediction: {
        prediction_id: 'prediction-1',
        symbol: 'AAPL',
        agent: 'prediction_analyst',
        direction: 'long',
        status: 'open',
        thesis: '服务收入增长仍是主要公开证据。',
        source_type: 'ai',
        evidence_provider: 'SEC 10-Q',
        evidence_as_of: '2026-09-14T20:00:00Z',
        created_at: '2026-09-15T00:00:00Z',
      },
      outcome: null,
    }],
  }));
  await page.route('**/api/predictions/stats**', (route) => fulfillJson(route, {
    stats: { predictions: 1, resolved: 0, hit_rate: null },
  }));

  await page.goto('/today');

  const quoteCard = page.getByTestId('today-watchlist-card');
  await expect(quoteCard).toContainText('233.42');
  await expect(quoteCard).toContainText('finnhub');
  await expect(quoteCard).toContainText('可信数据');
  const predictionCard = page.getByTestId('today-prediction-card');
  await expect(predictionCard).toContainText('SEC 10-Q');
  await expect(predictionCard).toContainText('服务收入增长仍是主要公开证据。');
  await expect(page.getByTestId('today-followup-item')).toBeVisible();

  await quoteCard.click();
  await expect(page).toHaveURL(/\/dashboard\/AAPL$/);
});

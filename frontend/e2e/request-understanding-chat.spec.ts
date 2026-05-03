import { expect, test } from '@playwright/test';

const fulfillJson = async (route: any, payload: unknown) => {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });
};

const parseRequestBody = (route: any) => {
  try {
    return JSON.parse(route.request().postData() || '{}');
  } catch {
    return {};
  }
};

const installCommonRoutes = async (page: any) => {
  await page.route('**/health', async (route: any) => {
    await fulfillJson(route, { status: 'ok' });
  });
  await page.route('**/api/stock/price/**', async (route: any) => {
    await fulfillJson(route, { success: true, data: { price: 180.5, change_percent: 1.2 } });
  });
  await page.route('**/api/chart/detect', async (route: any) => {
    await fulfillJson(route, { success: false, should_generate: false, ticker_candidates: [] });
  });
  await page.route('**/api/reports/index**', async (route: any) => {
    await fulfillJson(route, { success: true, count: 0, items: [] });
  });
  await page.route('**/api/reports/replay/**', async (route: any) => {
    await fulfillJson(route, { success: true, report: null, citations: [], trace_digest: {} });
  });
  await page.route('**/api/conversations/**', async (route: any) => {
    const body = parseRequestBody(route);
    await fulfillJson(route, {
      success: true,
      session_id: body.session_id || 'public:anonymous:e2e-request-understanding',
      cleared: { context: true },
      conversation: { turns: 0 },
    });
  });
  await page.route('**/api/user/profile**', async (route: any) => {
    await fulfillJson(route, { profile: { name: 'E2E User', watchlist: ['AAPL', 'MSFT'] } });
  });
  await page.route('**/api/subscriptions**', async (route: any) => {
    await fulfillJson(route, { subscriptions: [] });
  });
};

const fulfillTraceStream = async (route: any) => {
  const payload = parseRequestBody(route);
  const query = String(payload.query || '');
  const frames = [
    {
      type: 'trace',
      stage: 'understanding',
      summary: `拆解完成：${query || '空请求'}；识别公司、宏观和组合子任务`,
      tasks: [
        { id: 'task_1', subject_type: 'company', tickers: ['GOOGL'], operation: { name: 'fetch' } },
        { id: 'task_2', subject_type: 'macro', tickers: [], operation: { name: 'fact_check' } },
      ],
    },
    { type: 'token', content: `回答：${query}` },
    { type: 'done', response: `回答：${query}`, session_id: payload.session_id || 'public:anonymous:e2e-request-understanding' },
  ];
  await route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join(''),
  });
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-entry-mode', 'anonymous');
    localStorage.setItem('finsight-session-id', 'public:anonymous:e2e-request-understanding');
    localStorage.setItem('finsight-trace-view-mode', 'user');
  });
  await installCommonRoutes(page);
});

test('deep mode is enabled for aliases, ticker text, and macro questions without frontend alias dictionary', async ({ page }) => {
  await page.goto('/chat');

  const input = page.locator('#chat-input');
  const deepButton = page.getByTestId('chat-mode-deep-btn');
  const queries = [
    'GOOGL',
    'Apple',
    '谷歌',
    '微软',
    '苹果',
    '美联储利率路径对大型科技股估值有什么影响',
  ];

  for (const query of queries) {
    await input.fill(query);
    await expect(deepButton, `query should enable deep mode: ${query}`).toBeEnabled();
  }
});

test('chat conversations can be created, restored, and deleted from the rail', async ({ page }) => {
  page.on('dialog', async (dialog) => {
    await dialog.accept();
  });
  await page.route('**/chat/supervisor/stream', fulfillTraceStream);

  await page.goto('/chat');
  const chat = page.locator('#chat-scroll-container');

  const firstQuery = '第一轮：谷歌新闻和涨幅';
  await page.locator('#chat-input').fill(firstQuery);
  await page.getByTestId('chat-send-btn').click();
  await expect(chat.getByText(firstQuery, { exact: true })).toBeVisible();
  await expect(chat.getByText(`回答：${firstQuery}`)).toBeVisible();

  const firstItem = page.getByTestId('conversation-item').filter({ hasText: firstQuery }).first();
  await expect(firstItem).toBeVisible();
  const firstSessionId = await firstItem.getAttribute('data-session-id');
  expect(firstSessionId).toBeTruthy();

  await page.getByTestId('conversation-rail').locator('button[aria-label="新建对话"]').click();

  const secondQuery = '第二轮：微软新闻';
  await page.locator('#chat-input').fill(secondQuery);
  await page.getByTestId('chat-send-btn').click();
  await expect(chat.getByText(secondQuery, { exact: true })).toBeVisible();
  await expect(chat.getByText(`回答：${secondQuery}`)).toBeVisible();

  await page
    .locator(`[data-testid="conversation-item"][data-session-id="${firstSessionId}"]`)
    .locator('button')
    .first()
    .click();
  await expect(chat.getByText(firstQuery, { exact: true })).toBeVisible();
  await expect(chat.getByText(secondQuery, { exact: true })).toHaveCount(0);

  await page
    .locator(`[data-testid="conversation-item"][data-session-id="${firstSessionId}"]`)
    .getByTestId('conversation-delete')
    .click({ force: true });
  await expect(page.locator(`[data-testid="conversation-item"][data-session-id="${firstSessionId}"]`)).toHaveCount(0);
});

test('user trace view shows concrete backend understanding summaries', async ({ page }) => {
  await page.route('**/chat/supervisor/stream', fulfillTraceStream);

  await page.goto('/chat');
  const query = '你好，今天天气不错，帮我看看谷歌今天咋样，然后微软呢？';
  await page.locator('#chat-input').fill(query);
  await page.getByTestId('chat-send-btn').click();

  await page.getByRole('button', { name: /分析过程/ }).click();
  await expect(page.getByText('理解意图')).toBeVisible();
  await page.getByRole('button', { name: /理解意图/ }).click();
  await expect(page.getByText(`拆解完成：${query}；识别公司、宏观和组合子任务`)).toBeVisible();
});

test('running chat streams can be stopped from the input control', async ({ page }) => {
  await page.route('**/chat/supervisor/stream', async (route: any) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    try {
      await fulfillTraceStream(route);
    } catch {
      // The browser may abort the request before the mocked stream is fulfilled.
    }
  });

  await page.goto('/chat');
  await page.locator('#chat-input').fill('请持续分析 GOOGL 和 MSFT 的新闻');
  await page.getByTestId('chat-send-btn').click();

  await expect(page.getByTestId('chat-stop-btn')).toBeVisible();
  await page.getByTestId('chat-stop-btn').click();
  await expect(page.getByTestId('chat-send-btn')).toBeVisible();
  await expect(page.locator('#chat-scroll-container').getByText('已停止生成，保留已完成的结果。')).toBeVisible();
});

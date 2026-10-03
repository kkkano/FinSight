import { expect, test, type Page, type Route } from '@playwright/test';

const USER = 'persistence-user';
const SESSION = `public:${USER}:saved-thread`;
const ANSWER = 'INTC 的已验证研究要点：技术形态与风险需要分别评估，当前缺少有效价格锚点。';
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status,
  contentType: 'application/json', body: JSON.stringify(body) });

declare global {
  interface Window {
    emitPersistenceAuth: (event: string, user?: string) => void;
  }
}

async function setup(page: Page) {
  await page.addInitScript(({ sid }) => {
    if (sessionStorage.getItem('persistence-fixture-initialized')) return;
    sessionStorage.setItem('persistence-fixture-initialized', '1');
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-session-id', sid);
    localStorage.setItem(`finsight-messages:${sid}`, JSON.stringify([
      { id: 'prior-answer', role: 'assistant', content: 'Saved thread restored', timestamp: 1 },
    ]));
  }, { sid: SESSION });
  await page.route('**/src/api/supabaseClient.ts*', (route) => route.fulfill({
    contentType: 'application/javascript', body: `
      let session = { user: { id: '${USER}', email: null }, access_token: 'fixture-token' };
      let listener = () => {};
      window.emitPersistenceAuth = (event, user = '${USER}') => {
        session = user ? { user: { id: user, email: null }, access_token: 'fixture-token' } : null;
        listener(event, session);
      };
      const client = { auth: {
        getSession: async () => ({ data: { session } }),
        onAuthStateChange: (callback) => { listener = callback; return { data: { subscription: { unsubscribe() {} } } }; },
      } };
      export const getSupabaseClient = () => client;
      export const isSupabaseAuthConfigured = () => true;
    `,
  }));
  await page.route('**/health', (route) => json(route, { status: 'healthy' }));
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) return route.fallback();
    if (path === '/api/execute') {
      const body = route.request().postDataJSON();
      return route.fulfill({ contentType: 'text/event-stream', body: [
        { type: 'token', content: ANSWER }, { type: 'done', response: ANSWER, session_id: body.session_id },
      ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join('') });
    }
    return json(route, { success: true, items: [], messages: [], count: 0, models: [], profile: {} });
  });
}

async function snapshot(page: Page) {
  return page.evaluate(async () => {
    const modulePath = '/src/store/useStore.ts';
    const { useStore } = await import(modulePath);
    const state = useStore.getState();
    return { sessionId: state.sessionId, loading: state.isChatLoading,
      lastContent: state.messages.at(-1)?.content };
  });
}

test('首次认证与token刷新保留自己的已存会话', async ({ page }) => {
  await setup(page);
  await page.goto('/chat');
  await expect(page.locator('#chat-scroll-container').getByText('Saved thread restored', { exact: true })).toBeVisible();
  expect((await snapshot(page)).sessionId).toBe(SESSION);
  await page.evaluate(() => window.emitPersistenceAuth('TOKEN_REFRESHED'));
  await page.evaluate(() => window.emitPersistenceAuth('SIGNED_IN'));
  expect((await snapshot(page)).sessionId).toBe(SESSION);
  await expect(page.locator('#chat-scroll-container').getByText('Saved thread restored', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.locator('#chat-scroll-container').getByText('Saved thread restored', { exact: true })).toBeVisible();
  expect((await snapshot(page)).sessionId).toBe(SESSION);
});

test('旧快照未确认时合并最终回答，完成等待保存且刷新正文仍在', async ({ page }) => {
  await setup(page);
  let release: () => void = () => undefined;
  const first = new Promise<void>((resolve) => { release = resolve; });
  const snapshots: Array<{ messages: Array<{ role: string; content: string }> }> = [];
  let persisted: Array<{ role: string; content: string }> = [];
  await page.route('**/api/conversations', async (route) => {
    const body = route.request().postDataJSON();
    snapshots.push(body);
    if (snapshots.length === 1) await first;
    persisted = body.messages;
    await json(route, { success: true, session_id: body.session_id });
  });
  await page.goto('/chat');
  await page.getByRole('textbox', { name: '输入聊天消息' }).fill('分析一下 INTC');
  await page.getByRole('textbox', { name: '输入聊天消息' }).press('Enter');
  await expect(page.locator('#chat-scroll-container').getByText(ANSWER, { exact: true })).toBeVisible();
  await expect.poll(() => snapshots.length).toBe(1);
  expect((await snapshot(page)).loading).toBe(true);
  release();
  await expect.poll(async () => (await snapshot(page)).loading).toBe(false);
  expect(snapshots.length).toBe(2);
  expect(persisted.at(-1)).toMatchObject({ role: 'assistant', content: ANSWER });
  await page.reload();
  await expect(page.locator('#chat-scroll-container').getByText(ANSWER, { exact: true })).toBeVisible();
  expect((await snapshot(page)).sessionId).toBe(SESSION);
});

test('云端保存失败提示原因且不覆盖已生成的回答', async ({ page }) => {
  await setup(page);
  await page.route('**/api/conversations', (route) => {
    const body = route.request().postDataJSON();
    return body.messages.some((message: { content: string }) => message.content === ANSWER)
      ? json(route, { detail: 'fixture save failure' }, 503)
      : json(route, { success: true, session_id: body.session_id });
  });
  await page.goto('/chat');
  await page.getByRole('textbox', { name: '输入聊天消息' }).fill('分析一下 INTC');
  await page.getByRole('textbox', { name: '输入聊天消息' }).press('Enter');
  await expect(page.getByText('云端保存失败', { exact: true })).toBeVisible();
  await expect(page.locator('#chat-scroll-container').getByText(ANSWER, { exact: true })).toBeVisible();
  await expect.poll(async () => (await snapshot(page)).loading).toBe(false);
  expect((await snapshot(page)).lastContent).toBe(ANSWER);
  await page.reload();
  await expect(page.locator('#chat-scroll-container').getByText(ANSWER, { exact: true })).toBeVisible();
});

test('服务器已保存的最终正文不依赖浏览器快照写入', async ({ page }) => {
  await setup(page);
  let messages: Array<Record<string, unknown>> = [];
  await page.route('**/api/conversations', (route) => json(route, { detail: 'snapshot unavailable' }, 503));
  await page.route('**/api/conversations/**', (route) => json(route, { conversation: { messages } }));
  await page.route('**/api/execute', (route) => {
    const body = route.request().postDataJSON();
    expect(body.run_id).toBeTruthy();
    expect(body.client_user_message_id).toBeTruthy();
    expect(body.client_assistant_message_id).toBeTruthy();
    messages = [
      { id: body.client_user_message_id, role: 'user', content: body.query, timestamp: 10 },
      { id: body.client_assistant_message_id, role: 'assistant', content: ANSWER, timestamp: 11, run_id: body.run_id },
    ];
    return route.fulfill({ contentType: 'text/event-stream', body: [
      { type: 'token', content: '临时流式内容' },
      { type: 'done', response: ANSWER, session_id: body.session_id, persistence_status: 'saved',
        assistant_message: messages[1] },
    ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join('') });
  });
  await page.goto('/chat');
  await page.getByRole('textbox', { name: '输入聊天消息' }).fill('分析 INTC 的风险');
  await page.getByRole('textbox', { name: '输入聊天消息' }).press('Enter');
  await expect(page.locator('#chat-scroll-container').getByText(ANSWER, { exact: true })).toBeVisible();
  await expect(page.getByText('云端保存失败', { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.locator('#chat-scroll-container').getByText(ANSWER, { exact: true })).toBeVisible();
});

test('刷新后按run恢复回答且不重新触发模型', async ({ page }) => {
  await setup(page);
  let posts = 0;
  let reads = 0;
  await page.route('**/api/execute', (route) => { posts += 1; return json(route, { error: 'must not regenerate' }, 500); });
  await page.route('**/api/execute/runs/restore-run', (route) => {
    reads += 1;
    return json(route, { run_id: 'restore-run', session_id: SESSION, user_message_id: 'restore-user',
      assistant_message_id: 'restore-answer', status: reads === 1 ? 'running' : 'completed',
      result: reads === 1 ? null : { type: 'done', response: ANSWER, persistence_status: 'saved',
        assistant_message: { id: 'restore-answer', role: 'assistant', content: ANSWER } },
    });
  });
  await page.goto('/chat');
  await expect(page.locator('#chat-scroll-container').getByText('Saved thread restored', { exact: true })).toBeVisible();
  await page.evaluate(({ sid }) => {
    localStorage.setItem(`finsight-messages:${sid}`, JSON.stringify([
      { id: 'restore-user', role: 'user', content: '分析英特尔风险', timestamp: 10 },
      { id: 'restore-answer', role: 'assistant', content: '正在生成回答…', timestamp: 11,
        runId: 'restore-run', replyTo: 'restore-user', isLoading: true },
    ]));
  }, { sid: SESSION });
  await page.reload();
  await expect(page.locator('#chat-scroll-container').getByText(ANSWER, { exact: true })).toBeVisible();
  expect(posts).toBe(0);
  expect(reads).toBeGreaterThanOrEqual(2);
  await expect.poll(async () => (await snapshot(page)).loading).toBe(false);
});

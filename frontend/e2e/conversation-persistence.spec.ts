import { expect, test, type Page, type Route } from '@playwright/test';
import type { SendMessageBody, SSECallbacks } from '../src/api/contracts';
import type { StreamOpts } from '../src/api/sse';

const USER = 'persistence-user';
const SESSION = `public:${USER}:saved-thread`;
const ANSWER = 'INTC 的已验证研究要点：技术形态与风险需要分别评估，当前缺少有效价格锚点。';
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status,
  contentType: 'application/json', body: JSON.stringify(body) });

declare global {
  interface Window {
    emitPersistenceAuth: (event: string, user?: string) => void;
    deliveryFixture: { sends: number; reads: number; cancels: number; release?: () => void };
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

test('回答槽丢失且SSE挂住时保留99%交付状态并取回同轮已保存正文', async ({ page }) => {
  await setup(page);
  await page.goto('/chat');
  await expect(page.locator('#chat-scroll-container').getByText('Saved thread restored', { exact: true })).toBeVisible();
  await page.evaluate(async (answer) => {
    const apiPath = '/src/api/client.ts';
    const storePath = '/src/store/useStore.ts';
    const { apiClient } = await import(apiPath);
    const { useStore } = await import(storePath);
    const fixture = window.deliveryFixture = { sends: 0, reads: 0, cancels: 0,
      release: undefined as (() => void) | undefined };
    let request: SendMessageBody;
    apiClient.getExecutionRun = async () => {
      fixture.reads += 1;
      await new Promise<void>((resolve) => { fixture.release = resolve; });
      return { run_id: request.run_id, session_id: request.session_id, user_message_id: request.client_user_message_id,
        assistant_message_id: request.client_assistant_message_id, status: 'completed',
        result: { type: 'done', response: answer, persistence_status: 'saved', run_id: request.run_id,
          assistant_message: { id: request.client_assistant_message_id, content: answer } } };
    };
    apiClient.sendMessageStream = async (body: SendMessageBody, callbacks: SSECallbacks, opts: StreamOpts) => {
      fixture.sends += 1;
      request = body;
      useStore.setState({ messages: useStore.getState().messages.filter(
        (message: { id: string }) => message.id !== body.client_assistant_message_id,
      ) });
      callbacks.onThinking?.({ stage: 'rendering', eventType: 'pipeline_stage', runId: body.run_id,
        timestamp: new Date().toISOString(), result: { stage: 'rendering', status: 'done' } });
      callbacks.onToken?.('已收到本轮研究正文，等待服务器交付确认。');
      callbacks.onThinking?.({ stage: 'done', eventType: 'pipeline_stage', runId: body.run_id,
        timestamp: new Date().toISOString(), message: 'Execution completed', result: { stage: 'done', status: 'done' } });
      await new Promise<void>((resolve) => opts.signal!.addEventListener('abort', () => {
        if (opts.shouldCancelRunOnAbort?.() !== false) fixture.cancels += 1;
        resolve();
      }, { once: true }));
    };
  }, ANSWER);
  await page.getByRole('textbox', { name: '输入聊天消息' }).fill('分析 INTC 的基本面与风险');
  await page.getByRole('textbox', { name: '输入聊天消息' }).press('Enter');
  await expect(page.locator('#chat-scroll-container').getByText('已收到本轮研究正文，等待服务器交付确认。', { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.deliveryFixture.reads)).toBe(1);
  const pending = await page.evaluate(async () => {
    const executionPath = '/src/store/executionStore.ts';
    const { useExecutionStore } = await import(executionPath);
    const run = useExecutionStore.getState().activeRuns.at(-1);
    return { progress: run.progress, status: run.status, currentStep: run.currentStep };
  });
  expect(pending).toMatchObject({ progress: 99, status: 'running', currentStep: '正在保存并交付回答…' });
  expect((await snapshot(page)).loading).toBe(true);
  await page.evaluate(() => window.deliveryFixture.release!());
  await expect(page.locator('#chat-scroll-container').getByText(ANSWER, { exact: true })).toBeVisible();
  await expect.poll(async () => (await snapshot(page)).loading).toBe(false);
  expect(await page.evaluate(() => ({ sends: window.deliveryFixture.sends, cancels: window.deliveryFixture.cancels })))
    .toEqual({ sends: 1, cancels: 0 });
});

test('刷新旧客户端问题和空回答时恢复紧邻的同文canonical回答', async ({ page }) => {
  await setup(page);
  const query = '分析一下 英特尔 的最新基本面、技术面、催化剂与主要风险';
  const history = Array.from({ length: 8 }, (_, index) => ({ id: `legacy-history-${index}`,
    role: index % 2 === 0 ? 'user' : 'assistant', content: `Earlier saved turn ${index}`, timestamp: index + 1 }));
  const legacyUser = { id: 'legacy-user', role: 'user', content: query, timestamp: 1000 };
  const canonicalUser = { id: 'canonical-user', role: 'user', content: query,
    timestamp: 1000 + 9 * 3600000, run_id: 'legacy-saved-run' };
  const canonicalAnswer = { id: 'canonical-answer', role: 'assistant', content: ANSWER,
    timestamp: canonicalUser.timestamp + 1, run_id: canonicalUser.run_id, reply_to: canonicalUser.id };
  const repeatedUser = { ...canonicalUser, id: 'canonical-repeat-user', run_id: 'legacy-repeat-run' };
  const repeatedAnswer = { ...canonicalAnswer, id: 'canonical-repeat-answer', content: '第二轮 INTC 研究已保存，保留独立研究记录。',
    run_id: repeatedUser.run_id, reply_to: repeatedUser.id };
  let reads = 0;
  let writes = 0;
  await page.route('**/api/conversations/**', (route) => {
    reads += 1;
    return json(route, { success: true, session_id: SESSION,
      conversation: { messages: [...history, legacyUser, canonicalUser, canonicalAnswer, repeatedUser, repeatedAnswer] } });
  });
  await page.route('**/api/conversations', (route) => { writes += 1; return json(route, { success: true }); });
  await page.goto('/chat');
  await expect(page.locator('#chat-scroll-container').getByText('Saved thread restored', { exact: true })).toBeVisible();
  await page.evaluate(({ sid, history, legacyUser }) => {
    localStorage.setItem(`finsight-messages:${sid}`, JSON.stringify([...history, legacyUser,
      { id: 'empty-legacy-answer', role: 'assistant', content: '', timestamp: 1001, isLoading: true }]));
  }, { sid: SESSION, history, legacyUser });
  await page.reload();
  await expect(page.locator('#chat-scroll-container').getByText(ANSWER, { exact: true })).toBeVisible();
  await expect(page.locator('#chat-scroll-container').getByText(repeatedAnswer.content, { exact: true })).toBeVisible();
  await expect.poll(async () => (await snapshot(page)).loading).toBe(false);
  await expect(page.locator('#chat-scroll-container').getByText(query, { exact: true })).toHaveCount(2);
  expect(reads).toBeGreaterThan(0);
  expect(writes).toBe(0);
});

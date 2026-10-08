import { expect, test } from '@playwright/test';
import type { Page, Route } from '@playwright/test';

const builtIn = {
  id: 'stepfun:step-5-preview', label: 'Step 5 Preview', model: 'step-5-preview', provider: 'stepfun',
  icon_url: '/model-icons/stepfun.png', effort_options: ['low', 'medium', 'high'],
  default_effort: 'medium', available: true,
  docs_url: 'https://platform.stepfun.com/docs/zh/guides/models/step-5-preview',
};
const customKey = 'e2e-memory-only-key';

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
}

async function setup(page: Page, authenticated = true) {
  const testedModels: Record<string, unknown>[] = [];
  const chatModels: Record<string, unknown>[] = [];
  const predictionModels: Record<string, unknown>[] = [];
  const catalogHeaders: Array<string | undefined> = [];
  const configWrites: string[] = [];
  await page.addInitScript((hasSession) => {
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-entry-mode', hasSession ? 'pending' : 'anonymous');
    localStorage.setItem('finsight-session-id', 'public:anonymous:e2e-model-selection');
  }, authenticated);
  await page.route('**://*/api/**', async (route) => {
    if (!['fetch', 'xhr'].includes(route.request().resourceType())) return route.continue();
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/api/models') {
      catalogHeaders.push(route.request().headers()['x-finsight-model']);
      return fulfillJson(route, { models: [builtIn], default_model_id: builtIn.id });
    }
    if (pathname === '/api/models/capabilities') {
      catalogHeaders.push(route.request().headers()['x-finsight-model']);
      return fulfillJson(route, {
        provider: 'openai_compatible', label: 'OpenAI Compatible', icon_url: null,
        effort_options: [], default_effort: null, docs_url: null,
      });
    }
    if (pathname === '/api/models/test') {
      catalogHeaders.push(route.request().headers()['x-finsight-model']);
      testedModels.push(route.request().postDataJSON());
      return fulfillJson(route, { success: true, model: 'custom-model', latency_ms: 12, message: 'ok' });
    }
    if (pathname === '/api/predictions/generate') {
      const header = route.request().headers()['x-finsight-model'];
      predictionModels.push(header ? JSON.parse(Buffer.from(header, 'base64').toString('utf8')) : {});
      return fulfillJson(route, { run: { id: 'fixture-run', status: 'queued' } });
    }
    if (pathname === '/api/config' && route.request().method() === 'POST') configWrites.push(route.request().postData() || '');
    return fulfillJson(route, {
      success: true, items: [], count: 0, messages: [], skills: [], subscriptions: [],
      agents: [], data: {}, profile: { watchlist: [] }, should_generate: false,
    });
  });
  // Test-only identity and token. No real login or credentials are used.
  await page.route('**/src/api/supabaseClient.ts*', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `
      let signedIn = ${authenticated ? 'true' : 'false'};
      const listeners = new Set();
      const session = () => signedIn ? {
        access_token: 'e2e-fake-auth-token',
        user: { id: 'e2e-model-user', email: 'model-fixture@example.test' }
      } : null;
      const client = { auth: {
        getSession: async () => ({ data: { session: session() } }),
        onAuthStateChange: (callback) => {
          listeners.add(callback);
          return { data: { subscription: { unsubscribe: () => listeners.delete(callback) } } };
        },
        signOut: async () => {
          signedIn = false;
          for (const callback of listeners) callback('SIGNED_OUT', null);
          return { error: null };
        }
      } };
      export const getSupabaseClient = () => client;
      export const isSupabaseAuthConfigured = () => true;
    `,
  }));
  await page.route('**/health', (route) => fulfillJson(route, { status: 'ok' }));
  await page.route('**/diagnostics/**', (route) => fulfillJson(route, { status: 'ok' }));
  await page.route('**/api/execute', async (route) => {
    const header = route.request().headers()['x-finsight-model'];
    chatModels.push(header ? JSON.parse(Buffer.from(header, 'base64').toString('utf8')) : {});
    await route.fulfill({
      contentType: 'text/event-stream',
      body: 'data: {"type":"done","response":"模型测试回复"}\n\n',
    });
  });
  await page.goto(authenticated ? '/chat' : '/today');
  return { testedModels, chatModels, predictionModels, catalogHeaders, configWrites };
}

async function openModels(page: Page) {
  await expect(page.locator('[data-testid="chat-model-switcher"], [data-testid="sidebar-nav-settings"]').first()).toBeVisible();
  const button = page.getByTestId('chat-model-switcher');
  if (await button.count()) await button.click();
  else await page.getByTestId('sidebar-nav-settings').click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByLabel('内置模型')).toHaveValue(builtIn.id);
}

async function applyCustomModel(page: Page) {
  await page.getByRole('button', { name: '自带模型', exact: true }).click();
  await page.getByLabel('API 地址', { exact: true }).fill('https://api.example.com/v1');
  await page.getByLabel('模型 ID', { exact: true }).fill('custom-model');
  await page.getByLabel('API Key', { exact: true }).fill(customKey);
  await expect(page.getByRole('button', { name: '测试连接', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '测试连接', exact: true }).click();
  await expect(page.getByText(/连接成功/)).toBeVisible();
  await expect(page.getByRole('button', { name: '应用模型', exact: true })).toBeDisabled();
  await page.getByRole('checkbox', { name: '我已了解并同意将上述内容发送到填写的外部服务' }).check();
  await page.getByRole('button', { name: '应用模型', exact: true }).click();
}

async function sendChat(page: Page, query: string) {
  await page.getByRole('button', { name: '关闭设置', exact: true }).click();
  await page.locator('#chat-input').fill(query);
  await page.getByTestId('chat-send-btn').click();
  await expect(page.getByTestId('chat-send-btn')).toBeVisible();
}

test('built-in model uses official metadata and preserves the same model and effort across refresh and AI features', async ({ page }) => {
  const requests = await setup(page);
  await openModels(page);
  await expect(page.getByLabel('API Key', { exact: true })).toHaveCount(0);
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await expect(page.getByText('LLM Endpoints（轮换池）')).toHaveCount(0);
  await expect(page.getByLabel('推理强度')).toHaveValue('medium');
  await expect(page.getByLabel('推理强度').locator('option')).toHaveText(['low', 'medium', 'high']);
  await page.getByLabel('推理强度').selectOption('high');
  await page.getByRole('button', { name: '应用模型', exact: true }).click();
  await expect(page.getByTestId('current-model')).toContainText('Step 5 Preview');
  await sendChat(page, '你好');
  await expect(page.getByTestId('chat-model-switcher').locator('img')).toHaveAttribute('src', builtIn.icon_url);
  const selected = { source: 'system', model_id: builtIn.id, effort: 'high' };
  expect(requests.chatModels.at(-1)).toEqual(selected);
  expect(requests.testedModels).toHaveLength(0);
  expect(requests.configWrites).toHaveLength(0);
  await page.reload();
  await expect(page.getByTestId('chat-model-switcher')).toContainText('Step 5 Preview');
  await openModels(page);
  await expect(page.getByLabel('推理强度')).toHaveValue('high');
  await sendChat(page, '刷新后继续');
  expect(requests.chatModels.at(-1)).toEqual(selected);
  await page.evaluate(async () => {
    const modulePath = '/src/api/client.ts';
    const { apiClient } = await import(modulePath);
    await apiClient.generatePrediction('AAPL');
  });
  expect(requests.predictionModels.at(-1)).toEqual(selected);
});

test('custom model validates, requires testing, keeps a key-free preference on refresh, and never silently falls back', async ({ page }) => {
  const requests = await setup(page);
  await openModels(page);
  await page.getByRole('button', { name: '自带模型', exact: true }).click();
  await page.getByLabel('API 地址', { exact: true }).fill('invalid-url');
  await page.getByRole('button', { name: '测试连接', exact: true }).click();
  await expect(page.getByText('请输入完整的公共 HTTPS API 地址。')).toBeVisible();
  await expect(page.getByRole('button', { name: '应用模型', exact: true })).toBeDisabled();
  await expect(page.getByLabel('API Key', { exact: true })).toHaveAttribute('type', 'password');

  await applyCustomModel(page);
  await expect(page.getByLabel('推理强度')).toHaveCount(0);
  await expect(page.getByText('推理强度：供应商默认', { exact: true })).toBeVisible();
  await sendChat(page, '你好');
  const custom = { source: 'custom', base_url: 'https://api.example.com/v1', model: 'custom-model', api_key: customKey };
  expect(requests.testedModels.at(-1)).toEqual(custom);
  expect(requests.chatModels.at(-1)).toEqual({ ...custom, context_acknowledged: true });

  const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
  expect(storage).not.toContain(customKey);
  expect(storage).toContain('api.example.com');
  await page.getByTestId('chat-model-switcher').click();
  await page.getByRole('button', { name: '系统内置', exact: true }).click();
  await page.getByRole('button', { name: '应用模型', exact: true }).click();
  await sendChat(page, '继续');
  expect(requests.chatModels.at(-1)).toEqual({ source: 'system', model_id: builtIn.id, effort: 'medium' });

  await openModels(page);
  await applyCustomModel(page);
  await page.getByRole('button', { name: '关闭设置', exact: true }).click();
  await page.reload();
  await expect(page.getByTestId('chat-model-switcher')).toContainText('custom-model · 待补密钥');
  const countBeforeBlockedChat = requests.chatModels.length;
  await page.locator('#chat-input').fill('刷新后继续');
  await page.getByTestId('chat-send-btn').click();
  await expect(page.getByText('自带模型的密钥未保存。请在模型设置中重新填写 API Key、测试并应用，或明确选择内置模型。').first()).toBeVisible();
  expect(requests.chatModels).toHaveLength(countBeforeBlockedChat);
  await page.getByTestId('chat-model-switcher').click();
  await expect(page.getByLabel('API 地址', { exact: true })).toHaveValue('https://api.example.com/v1');
  await expect(page.getByLabel('API Key', { exact: true })).toHaveValue('');
  await expect(page.getByRole('button', { name: '应用模型', exact: true })).toBeDisabled();
  expect(requests.catalogHeaders.every((header) => header === undefined)).toBe(true);
  expect(requests.configWrites).toHaveLength(0);
});

test('anonymous users can inspect model settings and have a login entry for explicit selections', async ({ page }) => {
  const requests = await setup(page, false);
  await openModels(page);
  await expect(page.getByText('登录后才能测试或切换模型。', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: '测试连接', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '应用模型', exact: true })).toBeDisabled();
  expect(requests.chatModels).toHaveLength(0);
  await page.getByRole('button', { name: '自带模型', exact: true }).click();
  await expect(page.getByLabel('API Key', { exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '测试连接', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '应用模型', exact: true })).toBeDisabled();
  await page.getByRole('link', { name: '前往登录', exact: true }).click();
  await expect(page).toHaveURL(/\/welcome\?from=/);
  expect(requests.testedModels).toHaveLength(0);
});

test('custom context consent resets when destination credentials change and default restore removes the override', async ({ page }) => {
  const requests = await setup(page);
  await openModels(page);
  await page.getByRole('button', { name: '自带模型', exact: true }).click();
  const consent = page.getByRole('checkbox', { name: '我已了解并同意将上述内容发送到填写的外部服务' });
  await expect(consent).not.toBeChecked();
  await expect(page.getByTestId('custom-model-section')).toContainText('系统提示词、RAG 检索上下文及可能来自付费数据源的内容');
  for (const [label, value] of [
    ['API 地址', 'https://api.example.com/v1'], ['模型 ID', 'custom-model'], ['API Key', customKey],
  ]) {
    await consent.check();
    await page.getByLabel(label, { exact: true }).fill(value);
    await expect(consent).not.toBeChecked();
  }
  await expect(page.getByRole('button', { name: '测试连接', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '测试连接', exact: true }).click();
  await expect(page.getByText(/连接成功/)).toBeVisible();
  await expect(page.getByRole('button', { name: '应用模型', exact: true })).toBeDisabled();
  await consent.check();
  await page.getByRole('button', { name: '应用模型', exact: true }).click();
  await page.getByRole('button', { name: '恢复默认模型', exact: true }).click();
  await expect(page.getByTestId('current-model')).toContainText('Step 5 Preview');
  await sendChat(page, '你好');
  expect(requests.chatModels.at(-1)).toEqual({});
});

test('logout clears the applied custom selection and credentials', async ({ page }) => {
  await setup(page);
  await openModels(page);
  await applyCustomModel(page);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page).toHaveURL(/\/welcome(?:\?|$)/);
  const selection = await page.evaluate(async () => {
    const modulePath = '/src/store/modelSelection.ts';
    const { useModelSelectionStore } = await import(modulePath);
    return useModelSelectionStore.getState().selection;
  });
  expect(selection).toBeNull();
});

test('connection-test rate limits remain a recoverable form message', async ({ page }) => {
  await setup(page);
  await page.route('**/api/models/test', (route) => route.fulfill({
    status: 429, contentType: 'application/json', headers: { 'Retry-After': '30' },
    body: JSON.stringify({ detail: 'Test-only user rate limit' }),
  }));
  await openModels(page);
  await page.getByRole('button', { name: '测试连接', exact: true }).click();
  await expect(page.getByText('测试请求过于频繁，请稍后重试。', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button', { name: '测试连接', exact: true })).toBeEnabled();
});

test('model preflight failure and empty completions show explicit retryable messages', async ({ page }) => {
  await setup(page);
  await page.route('**/api/execute', (route) => route.fulfill({
    status: 503, contentType: 'application/json', body: JSON.stringify({
      detail: { code: 'model_unavailable', message: 'Step 5 Preview 暂时不可用，请稍后重试。' },
    }),
  }));
  await page.locator('#chat-input').fill('你好');
  await page.getByTestId('chat-send-btn').click();
  await expect(page.getByText('Step 5 Preview 暂时不可用，请稍后重试。').first()).toBeVisible();
  await expect(page.getByRole('button', { name: '重试回答', exact: true }).last()).toBeVisible();
  await page.route('**/api/execute', (route) => route.fulfill({
    contentType: 'text/event-stream', body: 'data: {"type":"done","response":""}\n\n',
  }));
  await page.getByRole('button', { name: '重试回答', exact: true }).last().click();
  await expect(page.getByText('模型未返回有效内容，本次分析未完成。请检查模型设置后重试。').first()).toBeVisible();
  await expect(page.getByTestId('chat-send-btn')).toBeVisible();
});

test('truncated model output keeps verified data and displays the actual cause', async ({ page }, testInfo) => {
  await setup(page);
  const message = '模型输出达到长度上限，回答被截断；本轮保留已核验数据，请重新生成。';
  await page.route('**/api/execute', (route) => route.fulfill({
    contentType: 'text/event-stream',
    body: [
      { type: 'degraded', stage: 'synthesis', reason: 'llm_output_truncated', message },
      { type: 'done', response: '已核验的英特尔研究数据。', degraded: true,
        degradation_reason: 'llm_output_truncated', degradation_message: message },
    ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
  }));
  await page.locator('#chat-input').fill('分析英特尔');
  await page.getByTestId('chat-send-btn').click();
  await expect(page.locator('#chat-scroll-container').getByText('已核验的英特尔研究数据。', { exact: true })).toBeVisible();
  await expect(page.getByText('本轮回答未完整生成', { exact: true })).toBeVisible();
  await expect(page.getByText(message, { exact: true }).first()).toBeVisible();
  await expect(page.getByText('LLM 暂时不可用', { exact: true })).toHaveCount(0);
  await expect(page.getByTestId('chat-send-btn')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('truncated-completion.png') });
});

test('canonical completion IDs do not move the answer out of the current conversation', async ({ page }) => {
  await setup(page);
  await page.route('**/api/execute', (route) => {
    const session = route.request().postDataJSON().session_id;
    return route.fulfill({ contentType: 'text/event-stream', body: `data: ${JSON.stringify({
      type: 'done', session_id: `${session}-canonical`, response: '当前会话中的英特尔研究回答',
    })}\n\n` });
  });
  await page.locator('#chat-input').fill('分析英特尔');
  await page.getByTestId('chat-send-btn').click();
  await expect(page.locator('#chat-scroll-container').getByText('分析英特尔', { exact: true })).toBeVisible();
  await expect(page.locator('#chat-scroll-container').getByText('当前会话中的英特尔研究回答', { exact: true })).toBeVisible();
});

test('answers remain visible and restore after refresh when local storage is full', async ({ page }, testInfo) => {
  await setup(page);
  let savedMessages: Array<{ id: string; role: string; content: string; timestamp: number }> = [];
  await page.route('**/api/conversations**', (route) => {
    const request = route.request();
    if (request.method() === 'POST') {
      const payload = request.postDataJSON();
      if (payload.messages) savedMessages = payload.messages;
      return fulfillJson(route, { success: true });
    }
    return fulfillJson(route, { success: true, conversation: { messages: savedMessages }, items: [] });
  });
  await page.evaluate(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith('finsight-messages:') || key === 'finsight-conversations') {
        throw new DOMException('Storage is full', 'QuotaExceededError');
      }
      original.call(this, key, value);
    };
  });
  await page.locator('#chat-input').fill('分析英特尔');
  await page.getByTestId('chat-send-btn').click();
  await expect(page.locator('#chat-scroll-container').getByText('模型测试回复', { exact: true })).toBeVisible();
  await expect.poll(() => savedMessages.some((message) => message.role === 'assistant' && message.content === '模型测试回复')).toBe(true);
  await page.reload();
  await expect(page.locator('#chat-scroll-container').getByText('模型测试回复', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('restored-answer-after-refresh.png') });
});

test('reopening an interrupted empty answer shows a visible retry state', async ({ page }) => {
  await setup(page);
  await page.evaluate(() => {
    const session = localStorage.getItem('finsight-session-id');
    localStorage.setItem(`finsight-messages:${session}`, JSON.stringify([
      { id: 'old-user', role: 'user', content: 'hi', timestamp: 1 },
      { id: 'old-answer', role: 'assistant', content: '', timestamp: 2, isLoading: true },
    ]));
  });
  await page.reload();
  await expect(page.locator('#chat-scroll-container').getByText('上次回答未完整保存，可以重新生成。', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '重试回答', exact: true }).last().click();
  await expect(page.locator('#chat-scroll-container').getByText('模型测试回复', { exact: true })).toBeVisible();
});

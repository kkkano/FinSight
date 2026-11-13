import { expect, test, type Locator, type Page, type Route } from '@playwright/test';
import fs from 'node:fs/promises';

// 受控验收只使用本地身份与资料，绝不把这些结果计作真实模型或线上验收。
const ALPHA = 'controlled-alpha';
const BETA = 'controlled-beta';
const SESSION = `public:${ALPHA}:default`;
const audits = new WeakMap<Page, { mockedApi: string[]; blockedExternal: string[]; pageErrors: string[] }>();
type Frame = Record<string, unknown>;

const json = (route: Route, body: unknown) => route.fulfill({
  contentType: 'application/json', body: JSON.stringify(body),
});

async function installControlledApp(page: Page, options: { seeded?: boolean; supportsTools?: boolean } = {}) {
  const audit = { mockedApi: [] as string[], blockedExternal: [] as string[], pageErrors: [] as string[] };
  audits.set(page, audit);
  page.on('pageerror', (error) => audit.pageErrors.push(error.message));
  await page.context().route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (['http:', 'https:'].includes(url.protocol) && !['127.0.0.1', 'localhost'].includes(url.hostname)) {
      audit.blockedExternal.push(url.origin + url.pathname);
      return route.abort('blockedbyclient');
    }
    return route.fallback();
  });
  await page.context().route('**/sw.js*', (route) => route.fulfill({
    contentType: 'application/javascript', body: "self.addEventListener('install', () => self.skipWaiting());",
  }));
  await page.addInitScript(({ alpha, beta, seeded }) => {
    if (!sessionStorage.getItem('controlled-acceptance-initialized')) {
      localStorage.clear();
      sessionStorage.setItem('controlled-acceptance-initialized', '1');
      sessionStorage.setItem('finsight-welcome-gate-passed', '1');
      localStorage.setItem('finsight-session-id', `public:${alpha}:default`);
      localStorage.setItem('finsight-theme', 'light');
      if (seeded) {
        for (const [owner, label] of [[alpha, '甲'], [beta, '乙']]) {
          localStorage.setItem(`finsight-messages:public:${owner}:default`, JSON.stringify([
            { id: `${owner}-question`, role: 'user', content: `${label}账号的问题`, timestamp: 1 },
            { id: `${owner}-answer`, role: 'assistant', content: `${label}账号独立保存的回答`, timestamp: 2 },
          ]));
        }
      }
    }
  }, { alpha: ALPHA, beta: BETA, seeded: options.seeded === true });
  await page.route('**/api/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return route.fallback();
    audit.mockedApi.push(`${request.method()} ${path}`);
    const owner = request.headers().authorization?.endsWith(BETA) ? BETA : ALPHA;
    const label = owner === ALPHA ? '甲' : '乙';
    if (path === '/api/models') return json(route, { default_model_id: 'system:controlled', models: [{
      id: 'system:controlled', label: '隔离验收模型', model: 'controlled-model', provider: 'system',
      available: true, native_tool_calls: options.supportsTools !== false,
      capability_status: options.supportsTools === false ? 'unsupported' : 'supported',
      vision: true, effort_options: [], default_effort: null,
    }] });
    if (path === '/api/skills') return json(route, { skills: [] });
    if (path === '/api/watchlist') return json(route, { items: [{
      ticker: owner === ALPHA ? 'AAPL' : 'MSFT', note: `${label}账号自选`,
    }] });
    if (path === '/api/predictions/history') return json(route, { items: [{ prediction: {
      prediction_id: `private-${owner}`, run_id: `prediction-${owner}`, symbol: owner === ALPHA ? 'AAPL' : 'MSFT',
      direction: 'long', status: 'open', source_type: 'ai', thesis: `${label}账号私有判断`,
      created_at: '2026-11-13T12:00:00Z', anchor: { price: 100, timeframe: '1d' },
      entry: 100, stop: 95, target1: 110, target2: 115, invalidation_price: 95,
      scenarios: [], prompt_version: 'controlled', evidence_provider: 'SEC', evidence_as_of: '2026-11-13T12:00:00Z',
    }, outcome: null }] });
    if (path === '/api/predictions/stats') return json(route, { stats: {
      days: 90, predictions: 1, resolved: 0, hits: 0, misses: 0, invalidated: 0, hit_rate: null,
      by_source: { ai: { predictions: 1, resolved: 0, hits: 0, misses: 0, invalidated: 0, hit_rate: null } },
    } });
    if (path.startsWith('/api/predictions/runs/')) return json(route, { run: { status: 'completed', llm_model: 'controlled-model' } });
    if (path === '/api/dashboard') return json(route, {
      success: true, state: { active_asset: { symbol: 'AAPL', display_name: 'Apple', type: 'equity' }, capabilities: {},
        watchlist: [], layout_prefs: { hidden_widgets: [], order: [] }, news_mode: { mode: 'market' } },
      data: { snapshot: {}, valuation: {}, charts: { market_chart: [] }, news: { market: [], impact: [] }, meta: {} },
    });
    if (path.startsWith('/api/stock/price/')) return json(route, { success: true, data: {
      price: 100, change_percent: 0, currency: 'USD', provider: 'SEC', as_of: '2026-11-13T12:00:00Z',
    } });
    if (path.endsWith('/cancel')) return json(route, { success: true, status: 'cancelled' });
    if (path.endsWith('/instructions')) return json(route, { status: 'accepted', instruction_id: 'controlled-instruction' });
    if (path.startsWith('/api/execute/runs/')) return json(route, {
      run_id: path.split('/').at(-1), session_id: `public:${owner}:default`, status: 'running', result: null,
    });
    if (path.startsWith('/api/conversations/') && request.method() === 'GET') return json(route, {
      success: true, conversation: { messages: [] },
    });
    return json(route, { success: true, session_id: SESSION, items: [], count: 0, messages: [],
      models: [], profile: {}, subscriptions: [], data: {}, agents: [] });
  });
  await page.route('**/health', (route) => json(route, { status: 'healthy' }));
  await page.route('**/src/api/supabaseClient.ts*', (route) => route.fulfill({
    contentType: 'application/javascript', body: `
      let owner = ${JSON.stringify(ALPHA)};
      const listeners = new Set();
      const session = () => ({ user: { id: owner, email: null }, access_token: 'controlled-local-token:' + owner });
      window.switchControlledIdentity = (next) => { owner = next; for (const callback of listeners) callback('SIGNED_IN', session()); };
      const client = { auth: {
        getSession: async () => ({ data: { session: session() } }),
        onAuthStateChange: (callback) => { listeners.add(callback); return { data: { subscription: { unsubscribe() { listeners.delete(callback); } } } }; },
      } };
      export const getSupabaseClient = () => client;
      export const isSupabaseAuthConfigured = () => true;
    `,
  }));
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    const encoder = new TextEncoder();
    let request: Record<string, unknown> = {};
    let controller: ReadableStreamDefaultController<Uint8Array> | undefined;
    let open = false;
    let seq = 0;
    let resumeResponse: ((response: Response) => void) | undefined;
    const fixture = {
      posts: [] as Record<string, unknown>[],
      resumes: [] as string[],
      frames: [] as Record<string, unknown>[],
      attemptedLateFrames: 0,
      disconnectAt: 0,
      reconnectAt: 0,
      emit(frame: Record<string, unknown>) {
        const nextSeq = typeof frame.seq === 'number' ? frame.seq : seq + 1;
        seq = Math.max(seq, nextSeq);
        const envelope = { schema_version: 2, run_id: request.run_id, session_id: request.session_id,
          seq: nextSeq, timestamp: new Date().toISOString(), ...frame };
        fixture.frames.push(envelope);
        if (!open || !controller) { fixture.attemptedLateFrames += 1; return; }
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(envelope)}\n\n`));
        if (['done', 'error', 'cancelled'].includes(String(frame.type))) { controller.close(); open = false; }
      },
      disconnect() {
        fixture.disconnectAt = Date.now();
        controller?.error(new TypeError('Controlled transport disconnected'));
        open = false;
      },
      resume() {
        fixture.reconnectAt = Date.now();
        if (!resumeResponse) throw new Error('No pending resume request');
        const stream = new ReadableStream<Uint8Array>({ start(next) { controller = next; open = true; } });
        resumeResponse(new Response(stream, { headers: { 'Content-Type': 'text/event-stream', 'X-Run-Id': String(request.run_id) } }));
      },
    };
    (window as unknown as { controlledAcceptance: typeof fixture }).controlledAcceptance = fixture;
    window.fetch = async (input, init) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
      if (url.pathname === '/api/execute' && init?.method === 'POST') {
        request = JSON.parse(String(init.body));
        fixture.posts.push(request);
        seq = 0;
        const stream = new ReadableStream<Uint8Array>({
          start(next) {
            controller = next; open = true;
            init.signal?.addEventListener('abort', () => {
              if (open) { open = false; next.error(new DOMException('Aborted', 'AbortError')); }
            }, { once: true });
          },
          cancel() { open = false; },
        });
        return new Response(stream, { headers: { 'Content-Type': 'text/event-stream', 'X-Run-Id': String(request.run_id) } });
      }
      if (url.pathname.startsWith('/api/execute/runs/') && url.pathname.endsWith('/events')) {
        fixture.resumes.push(url.pathname + url.search);
        return new Promise<Response>((resolve) => { resumeResponse = resolve; });
      }
      return originalFetch(input, init);
    };
  });
}

async function emit(page: Page, frame: Frame) {
  await page.evaluate((value) => (window as unknown as { controlledAcceptance: { emit: (frame: Frame) => void } }).controlledAcceptance.emit(value), frame);
}

async function send(page: Page, query = '分析 AAPL') {
  await page.goto('/chat');
  await expect(page.locator('#chat-input')).toBeVisible();
  await page.locator('#chat-input').fill(query);
  await page.getByTestId('chat-send-btn').click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { controlledAcceptance: { posts: unknown[] } }).controlledAcceptance.posts.length)).toBe(1);
}

async function finish(page: Page, response: string, extra: Frame = {}) {
  await emit(page, { type: 'done', response, persistence_status: 'saved', run_status: 'completed', ...extra });
  await expect(page.getByTestId('chat-stop-btn')).toHaveCount(0);
}

async function turnSnapshot(page: Page) {
  return page.evaluate(async () => {
    const modulePath = '/src/store/useStore.ts';
    const { useStore } = await import(modulePath);
    const state = useStore.getState();
    const last = state.messages.at(-1);
    return { sessionId: state.sessionId, loading: state.isChatLoading, messageCount: state.messages.length,
      last: last ? { id: last.id, content: last.content, runId: last.runId, runStatus: last.runStatus,
        answerStatus: last.answerStatus, report: last.report, timestamp: last.timestamp, thinking: last.thinking } : null };
  });
}

async function tabTo(page: Page, target: Locator) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (await target.evaluate((element) => element === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard cannot reach the requested control');
}

function artifact(scale: 'linear' | 'log' = 'linear') {
  return { artifact_id: 'controlled-chart', kind: 'chart', title: '隔离图表验收', dataset_refs: ['controlled-dataset'],
    source_refs: ['Sabc123'], spec: { chart_type: 'line', x: 'date', scale, series: [{ field: 'value', unit: 'USD' }] },
    data: { rows: [{ date: '2026-11-12', value: 100 }, { date: '2026-11-13', value: 110 }] },
    method: { frequency: 'daily', as_of: '2026-11-13', description: '受控资料，仅验证图表交互。' } };
}

const source = { source_id: 'Sabc123', title: '隔离财报资料', source: 'SEC', kind: 'document',
  url: 'https://www.sec.gov/controlled-acceptance', as_of: '2026-11-13T12:00:00Z' };

test.afterEach(async ({ page }, testInfo) => {
  const screenshotPath = testInfo.outputPath('final-state.png');
  await page.screenshot({ path: screenshotPath, fullPage: true });
  await testInfo.attach('final-state', { path: screenshotPath, contentType: 'image/png' });
  const fixture = await page.evaluate(() => {
    const value = (window as unknown as { controlledAcceptance?: Record<string, unknown> }).controlledAcceptance;
    return value ? { posts: value.posts, resumes: value.resumes, frames: value.frames,
      attemptedLateFrames: value.attemptedLateFrames, disconnectAt: value.disconnectAt, reconnectAt: value.reconnectAt } : null;
  });
  await testInfo.attach('controlled-evidence', { body: JSON.stringify({
    scope: 'local_ui_and_protocol_with_controlled_identity_and_data', onlineAcceptance: false,
    test: testInfo.title, status: testInfo.status, url: page.url(), audit: audits.get(page), fixture,
    aria: await page.locator('body').ariaSnapshot(),
  }, null, 2), contentType: 'application/json' });
  expect(audits.get(page)?.pageErrors ?? []).toEqual([]);
});

test('C1 displays a source timeout and the alternative source used in the answer', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'tool.started', payload: { name: 'get_stock_price', tool_call_id: 'failed-price',
    display: { title: '获取行情', target: 'AAPL' } } });
  await emit(page, { type: 'tool.failed', payload: { name: 'get_stock_price', tool_call_id: 'failed-price',
    status: 'error', error_code: 'TimeoutError', reason: 'Controlled source timeout', recovery_action: '改用原始披露资料。' } });
  await finish(page, '行情来源超时；已使用原始披露资料，盘中报价仍缺失。[Sabc123]', { evidence_pool: [source] });
  await page.getByLabel('研究过程').getByRole('button').first().click();
  const row = page.locator('.tool-activity').filter({ hasText: '获取行情' });
  await row.locator('summary').click();
  await expect(row).toContainText('处理超时');
  await expect(row).toContainText('改用原始披露资料');
  await expect(page.getByLabel('查看引用 1')).toBeVisible();
});

test('C2 preserves a partial answer and blocks publication when core data is missing', async ({ page }) => {
  await installControlledApp(page);
  await send(page, '为 AAPL 生成深度报告');
  await finish(page, '已有业务信息；缺少最近季度现金流，无法发布完整报告。', {
    run_status: 'partial', answer_status: 'partial', quality_blocked: true, publishable: false,
    query_coverage: { missing_required: ['最近季度现金流'] },
    blocked_report: { title: '不可发布的报告', summary: '缺少最近季度现金流' },
  });
  await expect(page.getByText('已有业务信息；缺少最近季度现金流，无法发布完整报告。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('research-status')).toContainText('部分结果');
  expect((await turnSnapshot(page)).last).toMatchObject({ runStatus: 'partial', answerStatus: 'partial' });
  expect((await turnSnapshot(page)).last?.report).toBeUndefined();
  await expect(page.getByRole('link', { name: '打开报告' })).toHaveCount(0);
});

test('C3 rejects a model with confirmed unsupported tool calling before sending', async ({ page }) => {
  await installControlledApp(page, { supportsTools: false });
  await page.goto('/chat');
  await expect(page.getByRole('alert').filter({ hasText: '不支持工具调用' })).toBeVisible();
  await page.locator('#chat-input').fill('AAPL 现在多少钱');
  await expect(page.getByTestId('chat-send-btn')).toBeDisabled();
  await expect(page.getByRole('button', { name: '更换模型', exact: true })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { controlledAcceptance: { posts: unknown[] } }).controlledAcceptance.posts)).toEqual([]);
});

test('C4 reconnects after thirty seconds into the original answer without duplicated text', async ({ page }, testInfo) => {
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'token', content: '断线前已生成的内容。' });
  await expect(page.getByText('断线前已生成的内容。', { exact: true })).toBeVisible();
  const original = await turnSnapshot(page);
  await page.evaluate(() => (window as unknown as { controlledAcceptance: { disconnect: () => void } }).controlledAcceptance.disconnect());
  await expect.poll(() => page.evaluate(() => (window as unknown as { controlledAcceptance: { resumes: string[] } }).controlledAcceptance.resumes.length)).toBe(1);
  await expect(page.getByTestId('chat-stop-btn')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('disconnected.png'), fullPage: true });
  // 这是指定的30秒断线场景，并非用等待掩盖断言或修复时序。
  await expect.poll(() => page.evaluate(() => {
    const fixture = (window as unknown as { controlledAcceptance: { disconnectAt: number } }).controlledAcceptance;
    return Date.now() - fixture.disconnectAt;
  }), { timeout: 35_000, intervals: [1000] }).toBeGreaterThanOrEqual(30_000);
  expect((await turnSnapshot(page)).loading).toBe(true);
  await page.evaluate(() => (window as unknown as { controlledAcceptance: { resume: () => void } }).controlledAcceptance.resume());
  await emit(page, { type: 'token', content: '断线前已生成的内容。', seq: 1 });
  await emit(page, { type: 'token', content: '重连后补充的内容。', seq: 2 });
  await expect(page.getByText('断线前已生成的内容。重连后补充的内容。', { exact: true })).toBeVisible();
  await finish(page, '断线前已生成的内容。重连后补充的内容。');
  const restored = await turnSnapshot(page);
  expect(restored.last?.id).toBe(original.last?.id);
  expect(restored.last?.runId).toBe(original.last?.runId);
  expect(restored.messageCount).toBe(original.messageCount);
  expect(await page.evaluate(() => {
    const fixture = (window as unknown as { controlledAcceptance: { posts: unknown[]; resumes: string[]; disconnectAt: number; reconnectAt: number } }).controlledAcceptance;
    return { posts: fixture.posts.length, cursor: fixture.resumes[0], disconnectedMs: fixture.reconnectAt - fixture.disconnectAt };
  })).toMatchObject({ posts: 1, cursor: expect.stringContaining('after_seq=1'), disconnectedMs: expect.any(Number) });
});

test('C5 stopping preserves generated content and ignores late tool and answer frames', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'token', content: '停止前已生成的内容。' });
  await expect(page.getByText('停止前已生成的内容。', { exact: true })).toBeVisible();
  await page.getByTestId('chat-stop-btn').click();
  await expect(page.getByTestId('research-status')).toContainText('已停止，保留已生成内容');
  await emit(page, { type: 'tool.result', payload: { tool_call_id: 'late', name: 'get_company_news', summary: '迟到工具结果' } });
  await emit(page, { type: 'token', content: '迟到的新增结论。' });
  expect((await turnSnapshot(page)).last).toMatchObject({ content: '停止前已生成的内容。', runStatus: 'cancelled' });
  await expect(page.getByText('迟到的新增结论。', { exact: true })).toHaveCount(0);
  await expect.poll(() => audits.get(page)?.mockedApi.filter((path) => path.endsWith('/cancel')).length).toBe(1);
});

test('C6 server save failure keeps the answer exportable and never records success', async ({ page }, testInfo) => {
  await installControlledApp(page);
  await send(page);
  const answer = '已生成、尚未保存的现金流分析。';
  await finish(page, answer, { persistence_status: 'failed', run_status: 'persistence_failed',
    answer_status: 'partial', publishable: false, error_code: 'conversation_persistence_failed' });
  await expect(page.getByRole('alert').filter({ hasText: '回答已生成，但未保存成功。' }).first()).toBeVisible();
  expect((await turnSnapshot(page)).last).toMatchObject({ content: answer, runStatus: 'persistence_failed' });
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出回答', exact: true }).last().click();
  const download = await downloadEvent;
  const target = testInfo.outputPath('unsaved-answer.md');
  await download.saveAs(target);
  expect(await fs.readFile(target, 'utf8')).toContain(answer);
  await testInfo.attach('exported-unsaved-answer', { path: target, contentType: 'text/markdown' });
  await expect(page.getByTestId('research-status')).toHaveText('保存失败');
});

test('C7 exhausted budget shows partial output and the remaining gap', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await finish(page, '已取得收入资料；研究预算耗尽，尚缺现金流核验。', {
    run_status: 'partial', answer_status: 'partial', publishable: false,
    error_code: 'agent_turn_budget_exhausted', query_coverage: { missing_required: ['现金流核验'] },
  });
  expect((await turnSnapshot(page)).last).toMatchObject({ runStatus: 'partial', answerStatus: 'partial' });
  await expect(page.getByTestId('research-status')).toContainText('部分结果');
  await expect(page.getByText('已取得收入资料；研究预算耗尽，尚缺现金流核验。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('research-status')).not.toContainText('分析完成');
});

test('B5 labels a logarithmic chart axis explicitly', async ({ page }) => {
  await installControlledApp(page);
  await send(page, '对数坐标图表');
  await emit(page, { type: 'artifact.ready', payload: { artifact: artifact('log') } });
  await finish(page, '以对数坐标显示隔离资料。', { evidence_pool: [source] });
  const figure = page.getByRole('figure', { name: '隔离图表验收' });
  await expect(figure.getByText('对数坐标', { exact: true })).toBeVisible();
  await expect(figure.locator('canvas')).toBeVisible();
});

test('B6 expands chart data and downloads the same rows as CSV', async ({ page }, testInfo) => {
  await installControlledApp(page);
  await send(page, '图表查看数据和下载');
  await emit(page, { type: 'artifact.ready', payload: { artifact: artifact() } });
  await finish(page, '可查看资料行并下载。', { evidence_pool: [source] });
  const figure = page.getByRole('figure', { name: '隔离图表验收' });
  await figure.getByRole('button', { name: '数据', exact: true }).click();
  await expect(figure.getByRole('table').filter({ has: page.getByRole('columnheader', { name: '日期', exact: true }) }).locator('tbody tr')).toHaveCount(2);
  const downloadEvent = page.waitForEvent('download');
  await figure.getByRole('button', { name: '下载', exact: true }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('controlled-chart.csv');
  const target = testInfo.outputPath('chart.csv');
  await download.saveAs(target);
  const csv = await fs.readFile(target, 'utf8');
  expect(csv.replace(/^\uFEFF/, '').split(/\r?\n/)).toEqual([
    '"date","value"', '"2026-11-12","100"', '"2026-11-13","110"',
  ]);
  await testInfo.attach('downloaded-chart-data', { path: target, contentType: 'text/csv' });
});

test('E1 contains wide tables and charts inside a 390px page', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'artifact.ready', payload: { artifact: artifact() } });
  await finish(page, '| 财务指标 | 最近季度详细说明与较长单位名称 | 对照季度详细说明与较长单位名称 |\n| --- | --- | --- |\n| 现金流 | 100 百万美元 | 110 百万美元 |');
  const figure = page.getByRole('figure', { name: '隔离图表验收' });
  await figure.getByRole('button', { name: '数据', exact: true }).click();
  await expect(figure.getByRole('table').filter({ has: page.getByRole('columnheader', { name: '日期', exact: true }) })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const containers = await page.locator('#chat-scroll-container table:visible').evaluateAll((tables) => tables.map((table) => {
    let parent = table.parentElement;
    while (parent && getComputedStyle(parent).overflowX !== 'auto') parent = parent.parentElement;
    return parent ? { overflow: getComputedStyle(parent).overflowX, width: parent.clientWidth } : null;
  }));
  expect(containers.length).toBeGreaterThanOrEqual(2);
  expect(containers.every((container) => container?.overflow === 'auto' && container.width <= 390)).toBe(true);
});

for (const variant of ['isComposing', 'keyCode229'] as const) {
  test(`E2 does not send Chinese composition Enter via ${variant}`, async ({ page }) => {
    await installControlledApp(page);
    await page.goto('/chat');
    const input = page.locator('#chat-input');
    await input.fill('分析苹果现金流');
    await input.dispatchEvent('compositionstart');
    await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true,
      isComposing: variant === 'isComposing', keyCode: variant === 'keyCode229' ? 229 : 13 });
    expect(await page.evaluate(() => (window as unknown as { controlledAcceptance: { posts: unknown[] } }).controlledAcceptance.posts.length)).toBe(0);
    await expect(input).toHaveValue('分析苹果现金流');
    await input.dispatchEvent('compositionend');
    await input.press('Enter');
    await expect.poll(() => page.evaluate(() => (window as unknown as { controlledAcceptance: { posts: unknown[] } }).controlledAcceptance.posts.length)).toBe(1);
    await finish(page, '组合输入完成后才发送。');
  });
}

test('E3 sends and stops an answer with keyboard controls and a visible focus ring', async ({ page }) => {
  await installControlledApp(page);
  await page.goto('/chat');
  const input = page.getByRole('textbox', { name: '输入聊天消息' });
  await tabTo(page, input);
  await page.keyboard.insertText('分析 AAPL');
  await page.keyboard.press('Enter');
  await expect.poll(() => page.evaluate(() => (window as unknown as { controlledAcceptance: { posts: unknown[] } }).controlledAcceptance.posts.length)).toBe(1);
  await emit(page, { type: 'token', content: '键盘停止保留此段。' });
  const stop = page.getByTestId('chat-stop-btn');
  await tabTo(page, stop);
  expect(await stop.evaluate((element) => ({ active: element === document.activeElement,
    width: parseFloat(getComputedStyle(element).outlineWidth), style: getComputedStyle(element).outlineStyle })))
    .toMatchObject({ active: true, style: 'solid', width: 2 });
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('research-status')).toContainText('已停止');
  expect((await turnSnapshot(page)).last?.content).toBe('键盘停止保留此段。');
});

test('E3 expands process and follows a source citation using only keyboard activation', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'tool.result', payload: { name: 'read_evidence', tool_call_id: 'read',
    display: { title: '读取资料', target: 'AAPL', status: 'ok' }, inputs: { ticker: 'AAPL' }, output_preview: '已读取现金流资料。' } });
  await finish(page, '财报来源可通过键盘访问。[Sabc123]', { evidence_pool: [source] });
  const toggle = page.getByLabel('研究过程').getByRole('button').first();
  await tabTo(page, toggle);
  await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  const citation = page.getByLabel('查看引用 1', { exact: true });
  await tabTo(page, citation);
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('context-panel')).toBeVisible();
  const highlightedSource = page.getByTestId('context-panel').locator('[data-source-id="Sabc123"]');
  await expect(highlightedSource).toHaveClass(/highlight/);
  await expect(highlightedSource).toBeVisible();
  expect(await page.evaluate(async () => {
    const path = '/src/store/citationNavigation.ts';
    const { useCitationNavigation } = await import(path);
    return useCitationNavigation.getState().focus?.sourceId;
  })).toBe('Sabc123');
});

test('E4 aria-live changes for activity and completion without announcing body tokens', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'tool.started', payload: { name: 'get_company_news', tool_call_id: 'news', label: '读取公司新闻' } });
  const status = page.getByTestId('research-status');
  await expect(status).toHaveAttribute('aria-live', 'polite');
  await expect(status).toHaveAttribute('aria-atomic', 'true');
  await expect(status).toContainText('读取公司新闻');
  const activityCaption = await status.textContent();
  await emit(page, { type: 'token', content: '正文第一段。' });
  await expect(page.getByText('正文第一段。', { exact: true })).toBeVisible();
  await expect(status).toHaveText(activityCaption!);
  await emit(page, { type: 'token', content: '正文第二段。' });
  await expect(page.getByText('正文第一段。正文第二段。', { exact: true })).toBeVisible();
  await expect(status).toHaveText(activityCaption!);
  await emit(page, { type: 'tool.result', payload: { name: 'get_company_news', tool_call_id: 'news', status: 'done' } });
  await finish(page, '正文第一段。正文第二段。');
  await expect(status).toHaveText('已处理');
  await expect(status).not.toContainText('正文');
});

test('E5 reduced-motion still permits send stop and process disclosure', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'tool.started', payload: { name: 'get_stock_price', tool_call_id: 'quote', label: '获取行情' } });
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true);
  expect(await page.locator('.turn-activity .animate-spin').evaluate((element) => parseFloat(getComputedStyle(element).animationDuration))).toBeLessThanOrEqual(0.001);
  const process = page.getByLabel('研究过程').getByRole('button').first();
  if (await process.getAttribute('aria-expanded') !== 'true') await process.click();
  await expect(page.locator('.tool-activity-row')).toHaveCount(1);
  await emit(page, { type: 'token', content: '减少动态效果时仍保留正文。' });
  await page.getByTestId('chat-stop-btn').click();
  await expect(page.getByTestId('research-status')).toContainText('已停止');
  expect((await turnSnapshot(page)).last?.content).toBe('减少动态效果时仍保留正文。');
});

test('F3 switching controlled accounts restores only the new owner conversation', async ({ page }) => {
  await installControlledApp(page, { seeded: true });
  await page.goto('/chat');
  await expect(page.getByText('甲账号独立保存的回答', { exact: true })).toBeVisible();
  await page.evaluate((owner) => (window as unknown as { switchControlledIdentity: (owner: string) => void }).switchControlledIdentity(owner), BETA);
  await expect(page.getByText('乙账号独立保存的回答', { exact: true })).toBeVisible();
  await expect(page.getByText('甲账号独立保存的回答', { exact: true })).toHaveCount(0);
  expect((await turnSnapshot(page)).sessionId).toBe(`public:${BETA}:default`);
});

test('F3 switching controlled accounts replaces the watchlist owner', async ({ page }) => {
  await installControlledApp(page);
  await page.goto('/dashboard/AAPL');
  const watchlist = page.getByLabel('自选与盯盘').locator('section').filter({ has: page.getByRole('heading', { name: '自选列表', exact: true }) });
  await expect(watchlist).toContainText('甲账号自选');
  await page.evaluate((owner) => (window as unknown as { switchControlledIdentity: (owner: string) => void }).switchControlledIdentity(owner), BETA);
  await expect(watchlist).toContainText('乙账号自选');
  await expect(watchlist).not.toContainText('甲账号自选');
});

test('F3 switching controlled accounts replaces private prediction history', async ({ page }) => {
  await installControlledApp(page);
  await page.goto('/history?view=predictions');
  await expect(page.getByTestId('prediction-history-item')).toContainText('甲账号私有判断');
  await page.evaluate((owner) => (window as unknown as { switchControlledIdentity: (owner: string) => void }).switchControlledIdentity(owner), BETA);
  await expect(page.getByTestId('prediction-history-item')).toContainText('乙账号私有判断');
  await expect(page.getByTestId('prediction-history-item')).not.toContainText('甲账号私有判断');
  await expect(page.getByTestId('prediction-history-detail')).not.toContainText('甲账号私有判断');
});

test('G1 completion duration and tool count agree with observed events', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  for (const id of ['quote', 'news']) {
    await emit(page, { type: 'tool.started', payload: { name: id === 'quote' ? 'get_stock_price' : 'get_company_news', tool_call_id: id } });
    await emit(page, { type: 'tool.result', payload: { name: id === 'quote' ? 'get_stock_price' : 'get_company_news', tool_call_id: id, status: 'done' } });
  }
  await finish(page, '研究活动计数与实际事件一致。');
  const last = (await turnSnapshot(page)).last!;
  const terminal = last.thinking.at(-1);
  const seconds = Math.max(0, Math.round((Date.parse(terminal.timestamp) - last.timestamp) / 1000));
  const summary = page.getByLabel('研究过程').getByRole('button').first();
  await expect(summary).toHaveText(`已处理 ${seconds} 秒 · 2 次工具调用`);
  await expect(summary).toHaveAttribute('aria-expanded', 'false');
  await summary.click();
  await expect(page.locator('.tool-activity-row')).toHaveCount(2);
});

test('G4 public reasoning summary remains collapsed after completion', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'reasoning.delta', payload: { block_id: 'public-summary', kind: 'summary', delta: '先核对财期和现金流定义。' } });
  await emit(page, { type: 'reasoning.finished', payload: { block_id: 'public-summary', kind: 'summary', duration_ms: 100 } });
  await finish(page, '财务口径已经核对。');
  const process = page.getByLabel('研究过程').getByRole('button').first();
  await expect(process).toBeVisible();
  await process.click();
  const block = page.getByTestId('reasoning-block').filter({ has: page.locator('[aria-expanded="false"]') });
  await expect(block).toHaveCount(1);
  await expect(page.getByTestId('reasoning-content')).toHaveCount(0);
  await block.getByRole('button').click();
  await expect(page.getByTestId('reasoning-content')).toHaveText('先核对财期和现金流定义。');
});

test('G4 provider raw reasoning requires the explicit account preference', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'reasoning.delta', payload: { block_id: 'provider-raw', kind: 'provider_raw', delta: '供应商返回的隔离原始字段。' } });
  await emit(page, { type: 'reasoning.finished', payload: { block_id: 'provider-raw', kind: 'provider_raw' } });
  await finish(page, '回答正文不受显示开关影响。');
  await expect(page.getByTestId('reasoning-block')).toHaveCount(0);
  await page.getByTestId('chat-model-switcher').click();
  await page.getByRole('checkbox', { name: '显示供应商原始推理', exact: true }).check();
  await page.getByRole('button', { name: '关闭设置', exact: true }).click();
  const process = page.getByLabel('研究过程').getByRole('button').first();
  await expect(process).toBeVisible();
  if (await process.getAttribute('aria-expanded') !== 'true') await process.click();
  await expect(page.getByTestId('reasoning-block')).toHaveCount(1);
  await expect(page.getByText('回答正文不受显示开关影响。', { exact: true })).toBeVisible();
  await page.getByTestId('reasoning-block').getByRole('button').click();
  await expect(page.getByTestId('reasoning-content')).toHaveText('供应商返回的隔离原始字段。');
});

test('G4 absent provider reasoning never creates a synthetic reasoning block', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await finish(page, '供应商只返回了正文。');
  await expect(page.getByTestId('reasoning-block')).toHaveCount(0);
  await expect(page.getByText('供应商只返回了正文。', { exact: true })).toBeVisible();
});

test('G5 successful quick capability validation never enters the process list', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'activity.started', payload: { activity_id: 'model_capability', title: '正在验证模型能力…' } });
  await emit(page, { type: 'activity.finished', payload: { activity_id: 'model_capability', title: '模型工具能力已验证', status: 'done' } });
  await finish(page, '模型验证通过后的正文。');
  await expect(page.getByText('模型工具能力已验证', { exact: true })).toHaveCount(0);
  const toggle = page.getByLabel('研究过程').getByRole('button').first();
  if (await toggle.count()) await toggle.click();
  await expect(page.locator('.tool-activity')).toHaveCount(0);
});

test('G5 capability validation appears only after two seconds or a confirmed failure', async ({ page }) => {
  await installControlledApp(page);
  await send(page);
  await emit(page, { type: 'activity.started', payload: { activity_id: 'model_capability', title: '正在验证模型能力…' } });
  const process = page.getByLabel('研究过程').getByRole('button').first();
  if (await process.getAttribute('aria-expanded') !== 'true') await process.click();
  await expect(page.locator('.tool-activity')).toHaveCount(0);
  await expect(page.locator('.tool-activity')).toHaveCount(1, { timeout: 5000 });
  await emit(page, { type: 'activity.error', payload: { activity_id: 'model_capability', error_code: 'model_tool_calling_unsupported', status: 'error' } });
  const row = page.locator('.tool-activity');
  await row.locator('summary').click();
  await expect(row).toContainText('当前模型不支持工具调用');
  await expect(row.getByRole('button', { name: '更换模型', exact: true })).toBeVisible();
  await finish(page, '模型不支持研究工具，研究已中断。', { run_status: 'failed', success: false, error_code: 'model_tool_calling_unsupported' });
});

test('D7 appearance and confirmation preferences apply immediately and survive refresh', async ({ page }) => {
  await installControlledApp(page);
  await page.goto('/chat');
  await page.getByTestId('chat-model-switcher').click();
  await page.getByRole('button', { name: '深色', exact: true }).click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.getByRole('radio', { name: '红涨绿跌', exact: true }).check();
  await page.getByRole('checkbox', { name: '自选增删免确认', exact: true }).check();
  await page.getByRole('button', { name: '关闭设置', exact: true }).click();
  await page.reload();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.getByTestId('chat-model-switcher').click();
  await expect(page.getByRole('radio', { name: '红涨绿跌', exact: true })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: '自选增删免确认', exact: true })).toBeChecked();
});

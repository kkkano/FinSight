import { expect, test } from '@playwright/test';
import { E2E_SESSION_ID, installAuthenticatedSession } from './helpers/auth';

test.beforeEach(async ({ page }) => {
  await page.addInitScript((sessionId) => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-session-id', sessionId);
    const realFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith('/api/execute') && init?.method === 'POST') {
        const request = JSON.parse(String(init.body));
        (window as unknown as { imageTestRequest: unknown }).imageTestRequest = request;
        let seq = 0;
        const encoder = new TextEncoder();
        const stream = new ReadableStream({
          start(controller) {
            const emit = (value: Record<string, unknown>) => controller.enqueue(encoder.encode('data: ' + JSON.stringify({
              schema_version: 2, run_id: request.run_id, session_id: request.session_id, seq: ++seq, ...value,
            }) + '\n\n'));
            emit({ type: 'tool.started', payload: { tool_call_id: 'quote-1', name: 'get_stock_price', label: '获取行情' } });
            setTimeout(() => emit({ type: 'tool.result', payload: { tool_call_id: 'quote-1', name: 'get_stock_price', label: '获取行情', summary: '已读取测试行情', status: 'done' } }), 40);
            setTimeout(() => emit({ type: 'token', runtime_type: 'content.delta', block_id: 'answer', content: '第一段正在生成。' }), 80);
            setTimeout(() => {
              emit({ type: 'token', runtime_type: 'content.delta', block_id: 'answer', content: '\n\n这是最终回答。' });
              emit({ type: 'artifact.ready', payload: { artifact: {
                artifact_id: 'chart-test', kind: 'chart', title: '测试数据比较', dataset_refs: ['fixture'],
                spec: { chart_type: 'line', x: 'date', series: [{ field: 'value', unit: 'USD' }] },
                data: { rows: [{ date: '2026-11-01', value: 100 }, { date: '2026-11-02', value: 105 }], panels: [
                  { title: '历史区间一', chart_type: 'line', rows: [{ date: '2026-11-01', value: 100 }, { date: '2026-11-02', value: 105 }] },
                  { title: '历史区间二', chart_type: 'candlestick', rows: [{ date: '2026-11-01', open: 100, close: 105, low: 99, high: 106 }] },
                ] },
                limitations: ['E2E固定数据，仅用于验证交互'],
              } } });
              emit({ type: 'done', response: '第一段正在生成。\n\n这是最终回答。', persistence_status: 'ephemeral', run_status: 'completed' });
              controller.close();
            }, 1800);
          },
        });
        return new Response(stream, { headers: { 'Content-Type': 'text/event-stream', 'X-Run-Id': request.run_id } });
      }
      return realFetch(input, init);
    };
  }, E2E_SESSION_ID);
  await installAuthenticatedSession(page);
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.fallback();
    const body = pathname === '/api/models' ? { models: [{
      id: 'system:server-default', model: 'test-model', provider: 'system', label: '测试模型',
      available: true, vision: true, effort_options: [], default_effort: null, icon_url: null, docs_url: null,
    }], default_model_id: 'system:server-default' }
      : pathname.endsWith('/instructions') ? { status: 'accepted', instruction_id: 'instruction-test' }
        : { success: true, items: [], watchlist: [], count: 0, profile: {}, conversation: { messages: [] } };
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"ok"}' }));
});

test('shows incremental body, settles one tool row and renders a real artifact block', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/chat');
  await page.locator('#chat-input').fill('看看AAPL的价格并画图');
  await page.getByTestId('chat-send-btn').click();
  await expect(page.getByText('第一段正在生成。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('chat-stop-btn')).toBeVisible();
  await expect(page.getByText('这是最终回答。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('chat-stop-btn')).toHaveCount(0);
  await expect(page.getByText('测试数据比较', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /已处理.*1 次工具调用/ }).click();
  await expect(page.locator('.tool-activity-row')).toHaveCount(1);
  await expect(page.getByText('获取行情', { exact: true })).toBeVisible();
  await expect(page.getByLabel('研究过程')).toHaveCount(1);
  await expect(page.getByLabel('历史区间对照')).toBeVisible();
  await expect(page.getByRole('heading', { name: '历史区间一' })).toBeVisible();
  await page.getByRole('button', { name: '放大图表', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '测试数据比较', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('event-study-panels.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: '测试数据比较', exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('chat-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: '切换到深色主题' }).click();
  await page.screenshot({ path: testInfo.outputPath('chat-desktop-dark.png'), fullPage: true });
});

test('sends an instruction into the active run without creating another user turn', async ({ page }) => {
  await page.goto('/chat');
  await page.locator('#chat-input').fill('研究AAPL');
  await page.getByTestId('chat-send-btn').click();
  await expect(page.getByText('第一段正在生成。', { exact: true })).toBeVisible();
  await page.locator('#chat-input').fill('只看现金流');
  const instruction = page.waitForRequest((request) => request.url().endsWith('/instructions'));
  await page.getByTestId('chat-steer-btn').click();
  expect((await instruction).postDataJSON().instruction).toBe('只看现金流');
  await expect(page.locator('#chat-input')).toHaveValue('');
  await expect(page.getByText('已收到补充要求', { exact: true })).toBeVisible();
  await expect(page.getByText('这是最终回答。', { exact: true })).toBeVisible();
});

test('keeps a narrow chat viewport within its screen and exposes navigation', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/chat');
  await expect(page.locator('#chat-input')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('chat-mobile.png'), fullPage: true });
});

test('content phases keep progress separate from the final answer', async ({ page }) => {
  await page.goto('/chat');
  await expect(page.locator('#chat-input')).toBeVisible();
  expect(await page.locator('body').ariaSnapshot()).toContain('textbox');
  await page.evaluate(async () => {
    const storePath = '/src/store/useStore.ts';
    const streamPath = '/src/store/researchStream.ts';
    const { useStore } = await import(storePath);
    const { applyResearchEvent, emptyResearchStream, researchText } = await import(streamPath);
    let stream = emptyResearchStream('phase-test');
    const events = [
      { type: 'content.delta', payload: { block_id: 'intro', delta: '我先查看现金流。' } },
      { type: 'content.block_finished', payload: { block_id: 'intro', content_phase: 'progress' } },
      { type: 'content.delta', payload: { block_id: 'candidate', delta: '待修正的旧说法。' } },
      { type: 'content.revised', payload: { block_id: 'candidate', content: '', revision: 1, content_phase: 'progress' } },
      { type: 'content.delta', payload: { block_id: 'final', delta: '正式结论只显示一次。' } },
      { type: 'content.block_finished', payload: { block_id: 'final', content_phase: 'answer' } },
    ];
    events.forEach((event, index) => { stream = applyResearchEvent(stream, { ...event, seq: index + 1, run_id: 'phase-test' }); });
    const timestamp = Date.now();
    useStore.setState({ messages: [
      { id: 'question', role: 'user', content: '分析 AAPL', timestamp },
      { id: 'answer', role: 'assistant', runId: 'phase-test', content: researchText(stream.blocks), blocks: stream.blocks,
        runStatus: 'completed', timestamp, isLoading: false },
    ] });
  });
  await expect(page.getByText('正式结论只显示一次。', { exact: true })).toHaveCount(1);
  await expect(page.getByText('我先查看现金流。', { exact: true })).toHaveCount(0);
  await expect(page.getByText('待修正的旧说法。', { exact: true })).toHaveCount(0);
  await page.getByLabel('研究过程', { exact: true }).getByRole('button').first().click();
  await expect(page.getByTestId('research-progress')).toHaveText('我先查看现金流。');
  await expect(page.getByText('正式结论只显示一次。', { exact: true })).toHaveCount(1);
});



test('PNG attachments preview, clear on send and never enter browser storage', async ({ page }) => {
  await page.goto('/chat');
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC', 'base64');
  await page.locator('#chat-image-input').setInputFiles({ name: '参考图.png', mimeType: 'image/png', buffer: png });
  await expect(page.getByRole('img', { name: '附件：参考图.png', exact: true })).toBeVisible();
  await expect(page.getByText(/发送给你选的模型/)).toBeVisible();
  expect(await page.evaluate(() => Object.values(localStorage).some((value) => value.includes('data:image/png;base64,')))).toBe(false);
  await page.locator('#chat-input').fill('分析这张图');
  await page.getByTestId('chat-send-btn').click();
  await expect(page.getByRole('img', { name: '附件：参考图.png', exact: true })).toHaveCount(0);
  const sent = await page.evaluate(() => (window as unknown as { imageTestRequest: { images?: { data_url: string; name: string }[] } }).imageTestRequest);
  expect(sent.images).toHaveLength(1);
  expect(sent.images![0].data_url).toMatch(/^data:image\/png;base64,/);
  expect(sent.images![0].name).toBe('参考图.png');
  expect(await page.evaluate(() => Object.values(localStorage).some((value) => value.includes('data:image/png;base64,')))).toBe(false);
  await expect(page.getByText('这是最终回答。', { exact: true })).toBeVisible();
});

test('PNG selection clears on a new conversation and enforces format and count', async ({ page }) => {
  await page.goto('/chat');
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC', 'base64');
  const input = page.locator('#chat-image-input');
  await input.setInputFiles({ name: '参考图.png', mimeType: 'image/png', buffer: png });
  await expect(page.getByRole('img', { name: '附件：参考图.png', exact: true })).toBeVisible();
  await page.getByTestId('sidebar').getByRole('button', { name: '新建对话', exact: true }).click();
  await expect(page.getByTestId('chat-image-attachments')).toHaveCount(0);
  await input.setInputFiles({ name: 'wrong.jpg', mimeType: 'image/jpeg', buffer: png });
  await expect(page.getByRole('alert').filter({ hasText: '仅支持 PNG' })).toBeVisible();
  await input.setInputFiles(Array.from({ length: 4 }, (_, index) => ({ name: index + '.png', mimeType: 'image/png', buffer: png })));
  await expect(page.getByRole('alert').filter({ hasText: '最多添加 3' })).toBeVisible();
  await expect(page.getByTestId('chat-image-attachments')).toHaveCount(0);
});

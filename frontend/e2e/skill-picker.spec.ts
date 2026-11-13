import { expect, test, type Page } from '@playwright/test';
import { E2E_SESSION_ID, installAuthenticatedSession } from './helpers/auth';

const skills = [
  { id: 'growth-quality', name: '成长质量', description: '分析增长持续性和盈利质量。', category: 'fundamental' },
  { id: 'ma-trend', name: '均线趋势', description: '分析均线和趋势。', category: 'technical' },
  { id: 'valuation-sanity-check', name: '估值合理性', description: '核查估值假设。', category: 'fundamental' },
  { id: 'wave-theory', name: '波浪理论', description: '分析价格波浪形态。', category: 'technical' },
];

async function prepare(page: Page) {
  const state = { requests: [] as Record<string, unknown>[], catalogueRequests: 0, failCatalogue: false };
  await page.addInitScript((sessionId) => {
    localStorage.clear();
    sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    localStorage.setItem('finsight-session-id', sessionId);
  }, E2E_SESSION_ID);
  await installAuthenticatedSession(page);
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.fallback();
    if (pathname === '/api/skills') {
      state.catalogueRequests += 1;
      return route.fulfill({ status: state.failCatalogue ? 503 : 200, contentType: 'application/json',
        body: JSON.stringify(state.failCatalogue ? { detail: 'unavailable' } : { skills }) });
    }
    if (pathname === '/api/execute') {
      const request = route.request().postDataJSON();
      state.requests.push(request);
      const events = [
        { type: 'skill.activated', payload: { skill_id: 'growth-quality', title: '成长质量', summary: '已应用成长质量研究方法。' } },
        { type: 'agent.started', agent_id: 'agent_abc123', payload: { agent_id: 'agent_abc123', role: 'fundamental_agent', task: '核查 AAPL 盈利预期' } },
        { type: 'tool.started', agent_id: 'agent_abc123', payload: { tool_call_id: 'estimates-1', name: 'get_earnings_estimates', inputs: { ticker: 'AAPL' } } },
        { type: 'tool.failed', agent_id: 'agent_abc123', payload: { tool_call_id: 'estimates-1', name: 'get_earnings_estimates',
          output_preview: { result_count: 0 }, sources: [{ title: '测试来源', url: 'https://example.com/earnings' }],
          reason: '该季度暂无盈利预期数据。', recovery_action: '可结合已取得的财报数据。', duration_ms: 1250 } },
        { type: 'agent.finished', agent_id: 'agent_abc123', payload: { agent_id: 'agent_abc123', role: 'fundamental_agent', status: 'completed', summary: '已核查财务资料。' } },
        { type: 'done', response: '研究结果已返回，盈利预期数据不足。', success: true, run_status: 'completed',
          answer_status: 'partial', quality: { reasons: [{ message: '盈利预期数据不足。' }] }, persistence_status: 'ephemeral' },
      ];
      return route.fulfill({ contentType: 'text/event-stream', headers: { 'X-Run-Id': request.run_id },
        body: events.map((event, index) => 'data: ' + JSON.stringify({ schema_version: 2, run_id: request.run_id,
          session_id: request.session_id, seq: index + 1, ...event }) + '\n\n').join('') });
    }
    const body = pathname === '/api/models' ? { models: [{ id: 'system:server-default', model: 'test-model', provider: 'system',
      label: '测试模型', available: true, native_tool_calls: true, effort_options: [], default_effort: null }], default_model_id: 'system:server-default' }
      : { success: true, items: [], watchlist: [], count: 0, profile: {}, conversation: { messages: [] } };
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"ok"}' }));
  await page.goto('/chat');
  await expect(page.locator('#chat-input')).toBeVisible();
  expect(await page.locator('body').ariaSnapshot()).toContain('textbox');
  return state;
}

test('selects real catalogue skills before sending and exposes readable specialist activity', async ({ page }, testInfo) => {
  const state = await prepare(page);
  const input = page.locator('#chat-input');
  expect(state.catalogueRequests).toBe(0);
  await input.fill('/');
  await expect(page.getByRole('option')).toHaveCount(skills.length);
  await page.screenshot({ path: testInfo.outputPath('skill-menu.png'), fullPage: true });
  await input.press('ArrowDown');
  await input.press('ArrowUp');
  await input.press('Enter');
  await expect(page.getByLabel('已选技能')).toContainText('成长质量');
  await expect(input).toHaveValue('');
  expect(state.requests).toHaveLength(0);
  await expect(page.getByTestId('chat-send-btn')).toBeDisabled();
  await input.fill('/MA-');
  await expect(page.getByRole('option')).toHaveCount(1);
  await input.press('Enter');
  await input.fill('分析 AAPL 成长质量');
  await input.press('Enter');
  await expect(page.getByText('研究结果已返回，盈利预期数据不足。', { exact: true })).toBeVisible();
  expect(state.requests[0]).toMatchObject({ query: '分析 AAPL 成长质量', skill_ids: ['growth-quality', 'ma-trend'] });
  expect(state.requests[0].resume_from_run_id).toBeUndefined();
  await expect(page.getByLabel('已选技能')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '从这里继续' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '重新研究' })).toHaveCount(1);
  await page.getByRole('button', { name: /已有部分结果，但资料还不完整/ }).click();
  await expect(page.getByText('成长质量', { exact: true })).toBeVisible();
  await page.locator('.tool-activity-row').filter({ hasText: '基本面分析师' }).click();
  await expect(page.locator('.tool-activity-row').filter({ hasText: '获取盈利预期' })).toBeVisible();
  await page.locator('.tool-activity-row').filter({ hasText: '获取盈利预期' }).click();
  await expect(page.getByText('参数', { exact: true })).toBeVisible();
  await expect(page.locator('.tool-activity-details').getByText('该季度暂无盈利预期数据。', { exact: true })).toBeVisible();
  await expect(page.locator('a[href="https://example.com/earnings"]')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('readable-activity.png'), fullPage: true });
  await input.fill('那现金流呢');
  await input.press('Enter');
  await expect.poll(() => state.requests.length).toBe(2);
  expect(state.requests[1].skill_ids).toBeUndefined();
  expect(state.requests[1].resume_from_run_id).toBeUndefined();
  expect(state.requests[1].query).toBe('那现金流呢');
});

test('filters Chinese names, caps selections, removes chips and clears them on another conversation', async ({ page }) => {
  const state = await prepare(page);
  const input = page.locator('#chat-input');
  for (const name of ['成长', '均线', '估值']) {
    await input.fill('/' + name);
    await expect(page.getByRole('option')).toHaveCount(1);
    await input.press('Enter');
  }
  await expect(page.getByLabel('已选技能').getByRole('button')).toHaveCount(3);
  await input.fill('/波浪');
  await expect(page.getByRole('option')).toHaveAttribute('aria-disabled', 'true');
  await input.press('Enter');
  expect(state.requests).toHaveLength(0);
  await page.getByRole('button', { name: '移除技能 成长质量' }).click();
  await input.press('Enter');
  await expect(page.getByLabel('已选技能')).toContainText('波浪理论');
  await page.getByTestId('sidebar').getByRole('button', { name: '新建对话', exact: true }).click();
  await expect(page.getByLabel('已选技能')).toHaveCount(0);
  await expect(page.getByTestId('skill-picker')).toHaveCount(0);
});

test('keeps failed or unmatched slash selection out of the conversation and supports retry and Escape', async ({ page }) => {
  const state = await prepare(page);
  state.failCatalogue = true;
  const input = page.locator('#chat-input');
  await input.fill('/');
  await expect(page.getByRole('alert').filter({ hasText: '技能列表暂时无法加载' })).toBeVisible();
  await input.press('Enter');
  expect(state.requests).toHaveLength(0);
  state.failCatalogue = false;
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page.getByRole('option')).toHaveCount(skills.length);
  await input.fill('/不存在');
  await expect(page.getByText('没有匹配的研究技能。')).toBeVisible();
  await input.press('Enter');
  await input.press('Escape');
  await expect(page.getByTestId('skill-picker')).toHaveCount(0);
  await expect(page.getByTestId('chat-send-btn')).toBeDisabled();
  expect(state.requests).toHaveLength(0);
});

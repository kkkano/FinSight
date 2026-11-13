import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { E2E_SESSION_ID, E2E_USER_ID, installAuthenticatedSession } from './helpers/auth';
import type { ResearchArtifact } from '../src/types/runtime';

const output = fileURLToPath(new URL('../../docs/reports/2026-11-13_ci_e2e/', import.meta.url));
mkdirSync(output, { recursive: true });
const progress = '先看价格，再计算这段时间的变化。';
const finalLead = '这是界面验收示例的最终回答。';
const finalAnswer = `${finalLead}\n\n新闻查询超时，信息还不完整。图表的数据和来源已列出。[Sa1b2c3d4e5]`;
const sources = [{ source_id: 'Sa1b2c3d4e5', title: '价格资料（前端验收示例）', source: '前端验收数据',
  url: 'https://example.com/ui-price-proof', as_of: '2026-11-07' }];
const artifact: ResearchArtifact = { artifact_id: 'ui-result-chart', kind: 'chart', title: '价格序列（前端验收示例）',
  source_refs: ['Sa1b2c3d4e5'], spec: { chart_type: 'line', x: 'date', series: [{ field: 'close', name: '示例价格', unit: 'USD' }] },
  data: { rows: [{ date: '2026-11-04', close: 100 }, { date: '2026-11-05', close: 104 }, { date: '2026-11-06', close: 103 }] },
  method: { description: '仅用于前端事件与显示验收，不是真实行情或后端研究结果。' } };

function buildEvents(runId: string, sessionId: string) {
  const frames: Array<Record<string, unknown>> = [];
  const emit = (type: string, payload: Record<string, unknown>) => {
    const seq = frames.length + 1;
    frames.push({ schema_version: 2, type, run_id: runId, session_id: sessionId, seq, payload });
    return seq;
  };
  const thoughtSeq = emit('reasoning.delta', { block_id: 'thought', kind: 'provider_raw', delta: '先了解问题，再看能拿到哪些资料。', agent_label: '主研究员' });
  const progressSeq = emit('content.delta', { block_id: 'progress', delta: progress });
  emit('content.block_finished', { block_id: 'progress', content_phase: 'progress' });
  const oldSeq = emit('content.delta', { block_id: 'old', delta: '这段旧候选应被删除。' });
  emit('content.revised', { block_id: 'old', content: '', revision: 1, content_phase: 'progress' });
  emit('tool.started', { tool_call_id: 'quote', name: 'get_stock_price', inputs: { ticker: 'AAPL' }, display: { target: 'AAPL', result: '' } });
  emit('tool.result', { tool_call_id: 'quote', name: 'get_stock_price', status: 'ok', duration_ms: 420,
    output_preview: { price: 103, currency: 'USD' }, display: { target: 'AAPL', result: '103 USD · 验收示例' }, sources });
  emit('agent.started', { agent_id: 'agent_a1b2c3', role: 'fundamental_agent', task: '检查现金流资料' });
  emit('tool.started', { tool_call_id: 'read', name: 'read_document', agent_id: 'agent_a1b2c3', inputs: { document_id: 'fixture-financials' } });
  emit('tool.result', { tool_call_id: 'read', name: 'read_document', agent_id: 'agent_a1b2c3', status: 'ok', duration_ms: 600,
    display: { target: '现金流样例', result: '2 条记录' }, output_preview: { result_count: 2 } });
  emit('agent.finished', { agent_id: 'agent_a1b2c3', role: 'fundamental_agent', status: 'completed', duration_ms: 800, summary: '资料已整理好。' });
  emit('tool.started', { tool_call_id: 'calculate', name: 'analyze_dataset', inputs: { operation: 'indexed_comparison' }, display: { target: '示例价格', result: '' } });
  emit('tool.result', { tool_call_id: 'calculate', name: 'analyze_dataset', status: 'ok', duration_ms: 180,
    display: { target: '示例价格', result: '3 点 · 区间 +3%' }, output_preview: { start: 100, end: 103, change_percent: 3 } });
  emit('tool.started', { tool_call_id: 'news', name: 'search', inputs: { query: 'AAPL 新闻' } });
  emit('tool.failed', { tool_call_id: 'news', name: 'search', status: 'unavailable', duration_ms: 2000,
    reason: '新闻服务连接超时。', error_code: 'source_timeout', recovery_action: '可以稍后重试新闻查询。',
    display: { target: 'AAPL 新闻', result: '连接超时' } });
  emit('tool.started', { tool_call_id: 'chart', name: 'render_chart', display: { target: '示例价格', result: '' } });
  emit('tool.result', { tool_call_id: 'chart', name: 'render_chart', status: 'ok', duration_ms: 120,
    display: { target: '示例价格', result: '折线 · 1 组数据 · 3 点' }, sources });
  const answerSeq = emit('content.delta', { block_id: 'answer', delta: finalAnswer });
  emit('content.block_finished', { block_id: 'answer', content_phase: 'answer' });
  const chartSeq = emit('artifact.ready', { artifact });
  frames.push({ type: 'done', run_id: runId, session_id: sessionId, seq: frames.length + 1, response: finalAnswer,
    success: true, run_status: 'completed', answer_status: 'partial', persistence_status: 'ephemeral',
    quality: { reasons: [{ code: 'partial_tool_failure', message: '新闻查询超时，相关信息还不完整。' }] }, evidence_pool: sources,
    blocks: [
      { id: 'thought', kind: 'reasoning', reasoning_kind: 'provider_raw', content: '先了解问题，再看能拿到哪些资料。', revision: 0, seq: thoughtSeq, duration_ms: 500, agent_label: '主研究员' },
      { id: 'progress', kind: 'text', content: progress, content_phase: 'progress', revision: 0, seq: progressSeq },
      { id: 'old', kind: 'text', content: '', content_phase: 'progress', revision: 1, seq: oldSeq },
      { id: artifact.artifact_id, kind: 'artifact', artifact, revision: 0, seq: chartSeq },
      { id: 'answer', kind: 'text', content: finalAnswer, content_phase: 'answer', revision: 0, seq: answerSeq },
    ] });
  return frames;
}

for (const variant of [{ name: 'light', dark: false, width: 1440 }, { name: 'dark', dark: true, width: 1440 }, { name: 'narrow', dark: false, width: 390 }]) {
  test(`result process icons ${variant.name}`, async ({ page }) => {
    let fixtureRequests = 0;
    let frames: Array<Record<string, unknown>> = [];
    await page.setViewportSize({ width: variant.width, height: 960 });
    await page.addInitScript(({ dark, sessionId, userId }) => {
      localStorage.clear(); localStorage.setItem('finsight-theme', dark ? 'dark' : 'light');
      localStorage.setItem(`finsight-research-preferences:${userId}`, JSON.stringify({ showProviderReasoning: true }));
      localStorage.setItem('finsight-session-id', sessionId); sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    }, { dark: variant.dark, sessionId: E2E_SESSION_ID, userId: E2E_USER_ID });
    await installAuthenticatedSession(page);
    await page.route('**/api/**', (route) => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.fallback();
      if (path === '/api/execute') {
        fixtureRequests += 1;
        const request = route.request().postDataJSON(); frames = buildEvents(request.run_id, request.session_id);
        return route.fulfill({ contentType: 'text/event-stream', body: frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('') });
      }
      const payload = path === '/api/capabilities' ? { ready: true, features: { retrieval: { mode: 'hybrid', full_ready: true } } }
        : path === '/api/models' ? { models: [{ id: 'system:server-default', model: 'fixture-model', label: '界面验收模型', provider: 'system', available: true, native_tool_calls: true, effort_options: [] }], default_model_id: 'system:server-default' }
          : { success: true, items: [], count: 0, data: {}, profile: {}, conversation: { messages: [] } };
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
    });
    await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"healthy"}' }));
    await page.goto('/chat'); await expect(page.locator('#chat-input')).toBeVisible();
    expect(await page.locator('body').ariaSnapshot()).toContain('textbox');
    await page.locator('#chat-input').fill('界面验收示例：分析 AAPL 的风险与机会');
    await page.getByTestId('chat-send-btn').click();
    await expect(page.getByText(finalLead, { exact: true })).toHaveCount(1);
    await expect(page.getByTestId('chat-stop-btn')).toHaveCount(0);
    await expect(page.getByTestId('research-progress')).toHaveCount(0);
    await expect(page.getByText('这段旧候选应被删除。', { exact: true })).toHaveCount(0);
    await expect(page.getByLabel('研究过程', { exact: true })).toContainText('已有部分结果，但资料还不完整');
    await page.getByLabel('研究过程', { exact: true }).getByRole('button').first().click();
    const progressBlock = page.getByTestId('research-progress');
    await expect(progressBlock).toHaveText(progress);
    await expect(progressBlock).toHaveCSS('font-size', '13px');
    const progressStyle = await progressBlock.evaluate((node) => ({ color: getComputedStyle(node).color, fontSize: getComputedStyle(node).fontSize, border: getComputedStyle(node).borderLeftWidth }));
    const answerStyle = await page.getByText(finalLead, { exact: true }).evaluate((node) => ({ color: getComputedStyle(node).color, fontSize: getComputedStyle(node).fontSize }));
    expect(Number.parseFloat(progressStyle.fontSize)).toBeLessThan(Number.parseFloat(answerStyle.fontSize));
    expect(progressStyle.color).not.toBe(answerStyle.color);
    expect(progressStyle.border).toBe('0px');
    await expect(progressBlock.locator('..')).toHaveCSS('border-left-width', '1px');
    await expect(page.getByText(finalLead, { exact: true })).toHaveCount(1);
    await expect(page.getByTestId('reasoning-block').getByRole('button')).toContainText('思考过程');

    const iconProof = [];
    for (const item of [
      { action: '获取行情', icon: 'lucide-trending-up', token: 'var(--t-amber)' },
      { action: '分析数据', icon: 'lucide-calculator', token: 'var(--t-violet)' },
      { action: '绘制图表', icon: 'lucide-chart-no-axes-combined', token: 'var(--t-teal)' },
      { action: '基本面分析师', icon: 'lucide-users', token: 'rgb(var(--t-accent))' },
    ]) {
      const row = page.locator('.tool-activity-row').filter({ hasText: item.action });
      await expect(row).toHaveCount(1);
      const icon = row.locator('svg').first(); await expect(icon).toHaveClass(new RegExp(item.icon));
      const color = await page.evaluate((token) => { const element = document.createElement('span'); element.style.color = token; document.body.append(element);
        const color = getComputedStyle(element).color; element.remove(); return color; }, item.token);
      await expect(icon).toHaveCSS('color', color);
      await expect(row.locator('svg.lucide-check')).toHaveCount(1);
      expect(await row.locator('.tool-activity-name').evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      iconProof.push({ ...item, color, text: await row.innerText() });
    }
    const failure = page.locator('.tool-activity-row').filter({ hasText: '搜索资料' });
    await expect(failure).toContainText('连接超时');
    await expect(failure.locator('svg.lucide-circle-alert')).toHaveCount(1);
    await expect(failure.locator('svg.lucide-check')).toHaveCount(0);
    await failure.click(); await expect(page.getByText('新闻服务连接超时。', { exact: true })).toBeVisible(); await failure.click();
    const agent = page.locator('.tool-activity-row').filter({ hasText: '基本面分析师' });
    await agent.click(); await expect(page.locator('.tool-activity-row').filter({ hasText: '读取文档' })).toBeVisible(); await agent.click();

    const chartData = await page.evaluate(async () => {
      const source = await (await fetch('/src/components/charts/EChartRuntime.tsx')).text();
      const path = [...source.matchAll(/from\s*["']([^"']+)["']/g)].map((match) => match[1]).find((path) => /\/echarts(?:\.js|\/)/.test(path))!;
      const echarts = await import(path); const element = document.querySelector('.research-artifact .echarts-for-react')!;
      return echarts.getInstanceByDom(element).getOption().series[0].data;
    });
    expect(chartData).toEqual(artifact.data!.rows!.map((row) => row.close));
    await expect(page.locator('.research-artifact')).toHaveCount(1);
    if (variant.width < 640) {
      const chartBox = (await page.locator('.research-artifact').boundingBox())!;
      const titleBox = (await page.locator('.research-artifact figcaption').boundingBox())!;
      expect(titleBox.width).toBeGreaterThan(chartBox.width * .75);
    }
    await expect(page.getByLabel('查看引用 1')).toHaveCount(1);
    await page.getByRole('region', { name: '回答来源' }).locator('summary').first().click();
    await expect(page.locator('a[href="https://example.com/ui-price-proof"]').filter({ visible: true })).toHaveCount(1);
    const visible = await page.locator('#chat-scroll-container').innerText();
    expect(visible).not.toMatch(/已撤回|本次供应商|思考供应商|显示.*供应商/);
    const stored = await page.evaluate(async () => { const path = '/src/store/useStore.ts'; return (await import(path)).useStore.getState().messages.at(-1); });
    expect(stored.content).toBe(finalAnswer); expect(stored.error).toBeUndefined(); expect(stored.answerStatus).toBe('partial');
    expect(stored.evidence_pool).toEqual(sources);
    expect(stored.blocks.find((block: { kind: string }) => block.kind === 'artifact').artifact).toEqual(artifact);
    await page.locator('#chat-scroll-container').evaluate((node) => { node.scrollTop = 0; });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: join(output, `result-process-icons-${variant.name}.png`), fullPage: false });
    writeFileSync(join(output, `result-process-icons-${variant.name}.json`), JSON.stringify({
      evidence_kind: 'frontend_event_fixture', not_live_backend_validation: true, real_model_calls: 0,
      mocked_execute_requests: fixtureRequests, viewport: { width: variant.width, height: 960 }, theme: variant.dark ? 'dark' : 'light',
      final_answer_occurrences: 1, final_content: stored.content, progress_separate: true, progress_style: progressStyle, answer_style: answerStyle,
      source_proof: sources, icons: iconProof, failed_tool: { name: 'search', reason: '新闻服务连接超时。', success_icon: false },
      chart_input_sha256: createHash('sha256').update(JSON.stringify(artifact)).digest('hex'), chart_rendered_values: chartData,
      chart_values_unchanged: true, frames,
    }, null, 2), 'utf8');
  });
}

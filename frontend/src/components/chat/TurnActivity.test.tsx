import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ActivityRow, buildTurnActivities, detailRows, TurnActivity } from './TurnActivity';
import type { ThinkingStep } from '../../types';

const step = (eventType: string, result: Record<string, unknown>): ThinkingStep => ({
  eventType: eventType as ThinkingStep['eventType'], stage: eventType, result, timestamp: '2026-11-06T10:00:00Z',
});
describe('turn activity projection', () => {
  it('provides useful details for an old model capability event with no payload', () => {
    const row = buildTurnActivities([step('activity.started', { activity_id: 'model_capability', title: '正在验证模型工具能力' })], true)[0];
    expect(renderToStaticMarkup(<ActivityRow row={row} />)).toContain('正在确认所选模型能否调用研究工具');
  });

  it('shows article titles and summaries rather than dumping nested provider metadata', () => {
    const row = buildTurnActivities([step('tool.result', { name: 'get_company_news', inputs: {}, output_preview: [
      { headline: '公司公布合作进展', url: 'https://example.com/news', source: 'Yahoo', published_at: '2026-11-09',
        summary: '这是一条相关报道摘要。', event_quality: { ingest_channel: 'provider_feed' } },
    ] })], false)[0];
    const html = renderToStaticMarkup(<ActivityRow row={row} />);
    expect(html).toContain('公司公布合作进展');
    expect(html).toContain('这是一条相关报道摘要。');
    expect(html).not.toContain('provider_feed');
    expect(html).not.toContain('font-medium">参数');
  });
  it('does not restart a terminal historical timer when an old loading flag survives', () => {
    const html = renderToStaticMarkup(<TurnActivity isLoading startedAt={Date.parse('2026-01-01T00:00:00Z')}
      runStatus="interrupted" />);
    expect(html).toContain('未完成');
    expect(html).not.toContain('正在处理你的问题');
    expect(html).not.toContain('animate-spin');
    expect(html).not.toMatch(/\d+ 秒/);
  });
  it('does not turn reopening history into an ever-growing research duration', () => {
    const html = renderToStaticMarkup(<TurnActivity thinking={[
      step('tool_end', { tool_call_id: 'saved', name: 'get_stock_price', status: 'ok', duration_ms: 300 }),
    ]} startedAt={Date.parse('2026-01-01T00:00:00Z')} runStatus="completed" />);
    expect(html).toContain('已完成');
    expect(html).not.toMatch(/已处理.*秒/);
  });
  it('settles the exact tool call in its original row', () => {
    const rows = buildTurnActivities([
      step('tool_start', { tool_call_id: 'call-1', name: 'get_stock_price' }),
      step('tool_end', { tool_call_id: 'call-1', name: 'get_stock_price', summary: '已有报价', duration_ms: 200 }),
    ], false);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ label: '获取行情', summary: '已有报价', status: 'done' });
  });
  it('does not manufacture successful steps from fixed pipeline transitions', () => {
    expect(buildTurnActivities([step('pipeline_stage', { stage: 'executing', status: 'done' })], false)).toEqual([]);
    expect(buildTurnActivities([step('tool_start', { tool_call_id: 'call-1', name: 'search' })], false)[0].status).toBe('cancelled');
  });
  it('keeps an explicit failure visible and excludes sensitive detail fields', () => {
    const row = buildTurnActivities([step('step_error', { tool_call_id: 'call-1', name: 'search', error: '来源不可用', api_key: 'not-for-display' })], false)[0];
    expect(row.status).toBe('error');
    expect(row.details.reason).toBe('来源不可用');
    expect(JSON.stringify(row.details)).not.toContain('not-for-display');
  });
  it('does not label unavailable or partial tool results as successful', () => {
    const rows = buildTurnActivities([
      step('tool_end', { tool_call_id: 'missing', name: 'search', status: 'unavailable' }),
      step('tool_end', { tool_call_id: 'partial', name: 'get_stock_price', status: 'partial' }),
    ], false);
    expect(rows.map((row) => row.status)).toEqual(['error', 'partial']);
  });

  it.each([
    ['discover_tools', '查找工具'], ['enable_tools', '启用工具'],
    ['read_evidence', '读取资料'], ['get_earnings_estimates', '获取盈利预期'],
  ])('renders the research tool %s in Chinese', (name, label) => {
    expect(buildTurnActivities([step('tool_start', { name })], true)[0].label).toBe(label);
  });

  it('preserves started inputs and renders bounded output, sources, duration and a useful failure', () => {
    const row = buildTurnActivities([
      step('tool_start', { tool_call_id: 'call-1', name: 'get_earnings_estimates',
        inputs: { ticker: 'AAPL', period: 'next_quarter', api_key: 'private-input' } }),
      step('step_error', { tool_call_id: 'call-1', name: 'get_earnings_estimates',
        output_preview: { result_count: 0, metadata: { authorization: 'private-output' } },
        sources: [{ title: '盈利预期来源', url: 'https://example.com/estimates' }],
        data_refs: ['data_1'], duration_ms: 1250, reason: '供应商没有返回该季度的盈利预期。',
        error_code: 'estimates_unavailable', recovery_action: '可尝试其他财务来源。' }),
    ], false)[0];
    expect(row.details.inputs).toEqual({ ticker: 'AAPL', period: 'next_quarter' });
    expect(row.summary).toBe('供应商没有返回该季度的盈利预期。');
    const markup = renderToStaticMarkup(<ActivityRow row={row} />);
    for (const content of ['参数', 'AAPL', '结果', '结果数量', '来源', '1.3 秒',
      '供应商没有返回该季度的盈利预期。', '可尝试其他财务来源。', 'estimates_unavailable']) expect(markup).toContain(content);
    expect(markup).toContain('href="https://example.com/estimates"');
    expect(markup).not.toMatch(/private-input|private-output|<pre/);
  });

  it('uses the actual specialist role and keeps its task when the finishing event omits it', () => {
    const rows = buildTurnActivities([
      step('agent_start', { agent_id: 'agent_abc123', role: 'fundamental_agent', task: '核查 AAPL 盈利预期' }),
      step('tool_start', { tool_call_id: 'call-1', agent_id: 'agent_abc123', name: 'get_earnings_estimates' }),
      step('agent_done', { agent_id: 'agent_abc123', status: 'completed', summary: '已核查两期预期' }),
    ], false);
    expect(rows[0]).toMatchObject({ label: '基本面分析师', summary: '核查 AAPL 盈利预期',
      details: { task: '核查 AAPL 盈利预期', output_preview: '已核查两期预期' } });
    expect(rows[1].agent).toBe(rows[0].agent);
    expect(buildTurnActivities([step('agent_start', { agent_id: 'agent_abc123' })], true)[0].label).toBe('专业研究员');
  });
  it('does not turn a legacy agent completion into a generic tool row sharing its step ID', () => {
    const rows = buildTurnActivities([step('agent_start', { step_id: 's1', agent: 'news_agent' }),
      step('step_done', { step_id: 's1', name: 'news_agent', kind: 'agent', duration_ms: 950 })], false);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ kind: 'agent', label: '新闻分析师', duration: 950, status: 'done' });
  });

  it('states when an old summary-only activity did not save details', () => {
    const row = buildTurnActivities([step('tool_end', { name: 'read_evidence', summary: '已取得结果', duration_ms: 1 })], false)[0];
    const markup = renderToStaticMarkup(<ActivityRow row={row} />);
    expect(markup).toContain('这条记录没有保存详细信息。');
    expect(markup).not.toContain('参数');
    expect(markup).not.toContain('font-medium">结果</p>');
    const legacy = buildTurnActivities([{ ...step('step_error', { name: 'get_earnings_estimates' }),
      message: 'step get_earnings_estimates error' }], false)[0];
    expect(legacy.summary).toBe('');
  });

  it('distinguishes completed research with evidence gaps from an interrupted run', () => {
    const markup = renderToStaticMarkup(<TurnActivity runStatus="completed" thinking={[
      { ...step('done', { status: 'partial' }), stage: 'done', message: '部分资料未取得。' },
    ]} />);
    expect(markup).toContain('已完成，部分信息待确认');
    expect(markup).not.toContain('未完成');
    expect(renderToStaticMarkup(<TurnActivity runStatus="failed" error="模型超时" />)).toContain('未完成');
  });

  it('shows an activated skill as a completed activity under its actual researcher', () => {
    const row = buildTurnActivities([step('trace', { runtime_type: 'skill.activated', skill_id: 'growth-quality',
      agent_id: 'agent_abc123', title: '成长质量', summary: '已应用成长质量研究方法。' })], false)[0];
    expect(row).toMatchObject({ label: '成长质量', status: 'done', kind: 'work', agent: 'agent_abc123' });
  });

  it('uses the tool display contract and hides routine model placeholder activities', () => {
    const rows = buildTurnActivities([
      step('trace', { runtime_type: 'activity.started', activity_id: 'root_model', summary: '正在分析已取得证据' }),
      step('tool_start', { tool_call_id: 'history', name: 'get_stock_historical_data', seq: 2, display: { target: 'AAPL · 日线 · 2025–2026', result: '' } }),
      step('tool_end', { tool_call_id: 'history', name: 'get_stock_historical_data', seq: 3, display: { target: 'AAPL · 日线 · 2025–2026', result: '252 根 · 200 → 220' } }),
    ], false);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ target: 'AAPL · 日线 · 2025–2026', summary: '252 根 · 200 → 220', seq: 2 });
    expect(detailRows(Array.from({ length: 50 }, (_, i) => ({ price: i })))).toHaveLength(10);
  });

  it('renders real ledger fallback titles and provider fields without internal identifiers', () => {
    const row = buildTurnActivities([step('tool_end', { name: 'get_stock_historical_data',
      inputs: { ticker: 'AAPL' }, display: { target: 'AAPL · 日线', result: '252 根行情' },
      output_preview: { source: 'twelve_data', provider: 'market_chart', tool: 'get_stock_historical_data' },
      sources: [
        { source_id: 'S1', title: 'twelve_data', source: 'twelve_data', url: 'https://twelvedata.com' },
        { source_id: 'S2', title: 'get_stock_historical_data', source: 'market_chart' },
        { source_id: 'S3', title: 'market_chart' },
        { source_id: 'S4', title: 'AAPL_2026_Q4：公司业绩公告' },
      ],
    })], false)[0];
    const visible = renderToStaticMarkup(<ActivityRow row={row} />).replace(/<[^>]+>/g, '');
    expect(visible).toContain('Twelve Data');
    expect(visible).toContain('历史行情数据');
    expect(visible).toContain('行情图表数据');
    expect(visible).toContain('AAPL_2026_Q4：公司业绩公告');
    expect(visible).not.toMatch(/twelve_data|market_chart|get_stock/);
  });

});


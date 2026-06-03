import { describe, expect, it } from 'vitest';

import {
  buildDailyCostOption,
  formatCompactNumber,
  formatUsd,
  normalizeCostAudit,
  sourceLabel,
  type CostAuditDailyPoint,
} from './costAudit';

const sampleResponse = {
  status: 'ok',
  data: {
    days: 7,
    daily: [
      {
        date: '2026-06-01',
        total_tokens: 1500,
        total_cost_usd: 0.12,
        request_count: 3,
        by_source: { chat: { tokens: 1000, cost_usd: 0.08, count: 2 }, report: { tokens: 500, cost_usd: 0.04, count: 1 } },
      },
      {
        date: '2026-06-02',
        total_tokens: 800,
        total_cost_usd: 0.05,
        request_count: 2,
        by_source: { dashboard: { tokens: 800, cost_usd: 0.05, count: 2 } },
      },
    ],
    top_requests: [
      { id: 2, created_at: '2026-06-02T10:00:00Z', session_id: 'big', source: 'report', total_tokens: 5000, prompt_tokens: 4000, completion_tokens: 1000, llm_calls: 8, cost_usd: 0.5, model_breakdown: { 'gpt-4o': { prompt: 4000, completion: 1000, calls: 8 } } },
      { id: 1, created_at: '2026-06-01T09:00:00Z', session_id: 'small', source: 'chat', total_tokens: 100, prompt_tokens: 60, completion_tokens: 40, llm_calls: 1, cost_usd: 0.001, model_breakdown: {} },
    ],
    total_cost_usd: 0.17,
    total_tokens: 2300,
    request_count: 5,
  },
  timestamp: '2026-06-02T12:00:00Z',
};

describe('normalizeCostAudit', () => {
  it('解析包裹在 {status, data} 中的响应', () => {
    const data = normalizeCostAudit(sampleResponse);
    expect(data.days).toBe(7);
    expect(data.daily).toHaveLength(2);
    expect(data.daily[0].by_source.chat.tokens).toBe(1000);
    expect(data.top_requests).toHaveLength(2);
    expect(data.top_requests[0].model_breakdown['gpt-4o'].prompt).toBe(4000);
    expect(data.total_cost_usd).toBe(0.17);
    expect(data.request_count).toBe(5);
  });

  it('解析裸 data 响应（无 status 包裹）', () => {
    const data = normalizeCostAudit(sampleResponse.data);
    expect(data.total_tokens).toBe(2300);
    expect(data.daily[1].date).toBe('2026-06-02');
  });

  it('对空/异常 payload 返回安全默认值', () => {
    expect(normalizeCostAudit(null).daily).toEqual([]);
    expect(normalizeCostAudit({}).total_tokens).toBe(0);
    expect(normalizeCostAudit({ data: { daily: 'bad', top_requests: null } }).top_requests).toEqual([]);
  });

  it('对缺字段的行回退为 0 / 空对象', () => {
    const data = normalizeCostAudit({ data: { daily: [{ date: '2026-06-03' }], top_requests: [{ id: 9 }] } });
    expect(data.daily[0].total_tokens).toBe(0);
    expect(data.daily[0].by_source).toEqual({});
    expect(data.top_requests[0].source).toBe('other');
    expect(data.top_requests[0].model_breakdown).toEqual({});
  });
});

describe('formatters', () => {
  it('formatCompactNumber 紧凑展示', () => {
    expect(formatCompactNumber(500)).toBe('500');
    expect(formatCompactNumber(1500)).toBe('1.5k');
    expect(formatCompactNumber(2_500_000)).toBe('2.50M');
    expect(formatCompactNumber(NaN)).toBe('—');
  });

  it('formatUsd 小额保留更多位避免归零', () => {
    expect(formatUsd(0)).toBe('$0');
    expect(formatUsd(0.0001)).toBe('$0.00010');
    expect(formatUsd(1.234)).toBe('$1.23');
  });

  it('sourceLabel 中文映射', () => {
    expect(sourceLabel('chat')).toBe('对话');
    expect(sourceLabel('monitor_l2')).toBe('盯盘深析');
    expect(sourceLabel('unknown_x')).toBe('unknown_x');
  });
});

describe('buildDailyCostOption', () => {
  const theme = {
    text: '#000',
    muted: '#888',
    border: '#ccc',
    grid: '#eee',
    primary: '#2563eb',
    warning: '#f59e0b',
    tooltipBackground: '#fff',
    tooltipBorder: '#ddd',
    tooltipText: '#000',
  };

  it('构建双轴 option：成本柱状 + token 折线', () => {
    const daily: CostAuditDailyPoint[] = [
      { date: '2026-06-01', total_tokens: 1500, total_cost_usd: 0.12, request_count: 3, by_source: {} },
      { date: '2026-06-02', total_tokens: 800, total_cost_usd: 0.05, request_count: 2, by_source: {} },
    ];
    const option = buildDailyCostOption(daily, theme) as any;
    expect(option.xAxis.data).toEqual(['2026-06-01', '2026-06-02']);
    expect(option.series[0].type).toBe('bar');
    expect(option.series[0].data).toEqual([0.12, 0.05]);
    expect(option.series[1].type).toBe('line');
    expect(option.series[1].data).toEqual([1500, 800]);
    expect(option.series[0].itemStyle.color).toBe('#2563eb');
  });

  it('空数据时 series data 为空数组', () => {
    const option = buildDailyCostOption([], theme) as any;
    expect(option.series[0].data).toEqual([]);
    expect(option.xAxis.data).toEqual([]);
  });
});

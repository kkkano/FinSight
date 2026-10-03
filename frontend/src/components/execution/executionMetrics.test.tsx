import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { ExecutionRun, TimelineEvent } from '../../types/execution';
import { formatExecutionDuration, summarizeExecutionMetrics } from './executionMetrics';
import { ExecutionStats } from './ExecutionStats';
import { ExecutionPanel } from './ExecutionPanel';
import { GroupedTimeline } from './GroupedTimeline';
import { formatTimelineTime } from './timelineUtils';
import * as executionStore from '../../store/executionStore';

function run(timeline: TimelineEvent[] = []): ExecutionRun {
  return {
    runId: 'run-metrics', query: '分析 AAPL', tickers: ['AAPL'], source: 'chat', outputMode: 'chat',
    status: 'done', agentStatuses: {}, progress: 100, currentStep: null, timeline,
    report: null, streamedContent: '', fallbackReasons: [], error: null,
    startedAt: '2026-10-02T00:00:00Z', completedAt: '2026-10-02T00:01:22Z', abortController: null,
  };
}

function event(id: string, overrides: Partial<TimelineEvent> = {}): TimelineEvent {
  return { id, timestamp: '2026-10-02T00:00:00Z', eventType: 'step_start', stage: 'executing', ...overrides };
}

describe('execution metrics', () => {
  it('从step事件取工具次数并按stepId去重完成步骤', () => {
    const sample = run([
      event('start-1', { stepId: 's1', kind: 'tool' }),
      event('done-1', { eventType: 'step_done', stepId: 's1', kind: 'tool', durationMs: 69_670 }),
      event('duplicate-done-1', { eventType: 'step_done', stepId: 's1', kind: 'tool', durationMs: 69_670 }),
      event('start-2', { stepId: 's2', kind: 'tool' }),
      event('done-2', { eventType: 'step_done', stepId: 's2', kind: 'tool', cached: true }),
      event('done-agent', { eventType: 'step_done', stepId: 's3', kind: 'agent' }),
    ]);
    const metrics = summarizeExecutionMetrics(sample);
    expect(metrics.toolCalls).toBe(2);
    expect(metrics.stepDone).toBe(3);
    expect(metrics.steps.find((step) => step.stepId === 's1')?.durationMs).toBe(69_670);
  });

  it('未采集的调用数显示未知，已有LLM汇总优先于事件', () => {
    expect(summarizeExecutionMetrics(run()).llmCalls).toBeNull();
    expect(summarizeExecutionMetrics(run()).toolCalls).toBeNull();
    const sample = run([event('llm-start', { eventType: 'llm_start' }), event('llm-call', { eventType: 'llm_call' })]);
    expect(summarizeExecutionMetrics(sample).llmCalls).toBe(1);
    sample.tokenUsage = { promptTokens: 20, completionTokens: 10, totalTokens: 30, costUsd: 0.001, llmCalls: 5 };
    expect(summarizeExecutionMetrics(sample).llmCalls).toBe(5);
    sample.tokenUsage.llmCalls = 0;
    expect(summarizeExecutionMetrics(sample).llmCalls).toBe(0);
    const html = renderToStaticMarkup(<ExecutionStats run={run()} />);
    expect(html).toContain('本轮未采集调用计数');
    expect(html).toContain('>—</dd>');
    expect(html).not.toContain('md:grid-cols-4');
  });

  it('完成耗时冻结，运行中的耗时使用当前时刻', () => {
    expect(formatExecutionDuration('2026-10-02T00:00:00Z', '2026-10-02T00:01:22Z', 0)).toBe('1 分 22 秒');
    expect(formatExecutionDuration('2026-10-02T00:00:00Z', null, Date.parse('2026-10-02T00:00:20Z'))).toBe('20 秒');
  });

  it('窄栏默认显示摘要、最耗时步骤和异常，执行详情保持折叠', () => {
    const previous = executionStore.useExecutionStore.getState();
    const sample = run([
      event('price-start', { stepId: 'price', kind: 'tool', name: 'get_stock_price' }),
      event('price-done', { eventType: 'step_done', stepId: 'price', kind: 'tool', name: 'get_stock_price', durationMs: 69_670 }),
    ]);
    sample.error = '行情供应商连接中断';
    sample.status = 'error';
    const storeState = { ...previous, activeRuns: [], recentRuns: [sample] };
    const storeMock = vi.spyOn(executionStore, 'useExecutionStore').mockImplementation((selector) => selector ? selector(storeState) : storeState);
    try {
      const html = renderToStaticMarkup(<ExecutionPanel compact />);
      expect(html).toContain('最耗时');
      expect(html).toContain('69.67s');
      expect(html).toContain('行情供应商连接中断');
      expect(html).toContain('本轮研究未完成');
      const detailsTag = html.match(/<details[^>]*data-testid="execution-details"[^>]*>/)?.[0];
      expect(detailsTag).toBeTruthy();
      expect(detailsTag).not.toContain('open=');
      expect(html).not.toContain('overflow-y-auto');
    } finally {
      storeMock.mockRestore();
    }
  });
});

describe('execution timeline', () => {
  it('重复Agent消息只显示一次并使用中文友好消息', () => {
    const timeline = Array.from({ length: 4 }, (_, index) => event(`agent-${index}`, {
      eventType: index === 3 ? 'agent_done' : 'agent_step', agent: 'technical_agent',
      message: 'technical Agent', userMessage: '技术指标分析完成',
    }));
    const html = renderToStaticMarkup(<GroupedTimeline timeline={timeline} compact />);
    expect(html.match(/技术指标分析完成/g)).toHaveLength(1);
    expect(html).toContain('技术分析');
    expect(html).not.toContain('technical Agent');
    expect(html).not.toContain('overflow-y-auto');
  });

  it('带时区的时间转换为浏览器本地时间并统一24小时格式', () => {
    const expected = new Date('2026-10-02T00:00:00Z').toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    expect(formatTimelineTime('2026-10-02T00:00:00Z')).toBe(expected);
    expect(formatTimelineTime('2026-10-02T08:00:00+08:00')).toBe(expected);
  });
});

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { AgentProfileMap } from '../../types/agents';
import type { ExecutionRun } from '../../types/execution';
import { AgentWorkLog } from './AgentWorkLog';

const profiles: AgentProfileMap = Object.fromEntries([
  ['fundamental_agent', '基本面分析师', '基本面', 'F', 't-info'],
  ['news_agent', '新闻分析师', '新闻', 'N', 't-warn'],
  ['risk_agent', '风险分析师', '风险', 'R', 't-down'],
].map(([name, displayName, shortName, glyph, colorToken]) => [name, {
  name,
  display_name: displayName,
  short_zh: shortName,
  description: displayName,
  glyph,
  color_token: colorToken,
  mandate: displayName,
  insert_text: `@${name} `,
}]));

function buildRun(overrides: Partial<ExecutionRun> = {}): ExecutionRun {
  return {
    runId: 'run-work-log',
    query: '分析 AAPL',
    tickers: ['AAPL'],
    source: 'chat',
    outputMode: 'brief',
    status: 'running',
    agentStatuses: {
      fundamental_agent: {
        name: 'fundamental_agent',
        status: 'running',
        currentStep: '检索 8 季度财报',
        durationMs: 12_400,
      },
      news_agent: {
        name: 'news_agent',
        status: 'done',
        currentStep: '核验公告',
        durationMs: 4_200,
      },
      risk_agent: {
        name: 'risk_agent',
        status: 'error',
        currentStep: '计算风险暴露',
        durationMs: 2_100,
      },
    },
    selectedAgents: ['fundamental_agent', 'news_agent', 'risk_agent'],
    planSteps: [],
    progress: 50,
    currentStep: '执行中',
    timeline: [],
    report: null,
    streamedContent: '',
    fallbackReasons: [],
    error: null,
    startedAt: '2026-07-12T00:00:00.000Z',
    completedAt: null,
    abortController: null,
    ...overrides,
  };
}

describe('AgentWorkLog', () => {
  it('renders running, done and error rows with honest actions and durations', () => {
    const html = renderToStaticMarkup(<AgentWorkLog run={buildRun()} profiles={profiles} />);
    expect(html).toContain('基本面');
    expect(html).toContain('title="基本面分析师"');
    expect(html).toContain('>F</span>');
    expect(html).toContain('检索 8 季度财报');
    expect(html).toContain('12.4s');
    expect(html).toContain('aria-label="运行中"');
    expect(html).toContain('aria-label="已完成"');
    expect(html).toContain('aria-label="失败"');
  });

  it('collapses a terminal run into agent, tool-call and elapsed summary', () => {
    const timeline = Array.from({ length: 23 }, (_, index) => ({
      id: `tool-${index}`,
      timestamp: '2026-07-12T00:00:01.000Z',
      eventType: 'tool_start',
      stage: 'tool_start',
    }));
    const html = renderToStaticMarkup(
      <AgentWorkLog
        run={buildRun({
          status: 'done',
          timeline,
          completedAt: '2026-07-12T00:01:24.000Z',
        })}
      />,
    );
    expect(html).toContain('3 个智能体 · 23 次取数 ·');
    expect(html).toContain('1m24s');
    expect(html).not.toContain('检索 8 季度财报');
  });
});

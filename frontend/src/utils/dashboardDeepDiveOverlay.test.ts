import { describe, expect, it } from 'vitest';

import {
  buildDashboardOverlayKey,
  buildDashboardAgentOverlay,
  dashboardChartSpecsToBlocks,
} from './dashboardDeepDiveOverlay';
import type { ExecutionRun } from '../types/execution';
import type { ReportIR } from '../types';

function buildRun(overrides: Partial<ExecutionRun> = {}): ExecutionRun {
  return {
    runId: 'run-1',
    query: 'Dashboard Deep Dive',
    tickers: ['AAPL'],
    source: 'dashboard_deep_dive_technical',
    outputMode: 'investment_report',
    analysisDepth: 'report',
    status: 'done',
    agentStatuses: {},
    pipelineCurrentStage: 'done',
    selectedAgents: [],
    skippedAgents: [],
    planSteps: [],
    hasParallelPlan: false,
    etaSeconds: null,
    progress: 100,
    currentStep: null,
    timeline: [],
    report: null,
    streamedContent: '',
    fallbackReasons: [],
    error: null,
    startedAt: '2026-05-31T00:00:00.000Z',
    completedAt: '2026-05-31T00:01:00.000Z',
    abortController: null,
    bridgedToChat: false,
    interruptData: null,
    ...overrides,
  };
}

describe('dashboardDeepDiveOverlay', () => {
  it('normalizes symbol-tab overlay keys', () => {
    expect(buildDashboardOverlayKey(' aapl ', 'technical')).toBe('AAPL_technical');
  });

  it('extracts summary, claims, and chartSpecs from completed runs', () => {
    const report = {
      report_id: 'r1',
      ticker: 'AAPL',
      company_name: 'Apple',
      title: 'AAPL 技术面深挖',
      summary: '趋势偏强，但需要成交量继续确认。',
      sentiment: 'bullish',
      confidence_score: 0.78,
      generated_at: '2026-05-31T00:01:00.000Z',
      sections: [],
      citations: [],
      evidence_ledger: {
        ledger_id: 'ledger-1',
        claims: [
          {
            claim_id: 'claim-1',
            claim: '价格动量仍在均线上方。',
            confidence: 0.76,
          },
        ],
      },
      meta: {
        dashboard_overlay: {
          chart_specs: [
            {
              type: 'line',
              title: '动量路径',
              data: { labels: ['D1', 'D2'], values: [1, 2] },
            },
          ],
        },
      },
    } satisfies ReportIR;

    const overlay = buildDashboardAgentOverlay(buildRun({ report }), '2026-05-31T00:02:00.000Z');

    expect(overlay.summary).toContain('趋势偏强');
    expect(overlay.claims).toHaveLength(1);
    expect(overlay.claims[0].claim).toBe('价格动量仍在均线上方。');
    expect(overlay.chartSpecs).toHaveLength(1);
    expect(overlay.updatedAt).toBe('2026-05-31T00:02:00.000Z');
  });

  it('converts chart specs into SmartChart inline blocks', () => {
    const blocks = dashboardChartSpecsToBlocks([
      {
        type: 'bar',
        title: '收入对比',
        data: { labels: ['A', 'B'], values: [10, 12] },
      },
    ]);

    expect(blocks).toEqual([
      {
        mode: 'inline',
        type: 'bar',
        title: '收入对比',
        dataJson: '{"labels":["A","B"],"values":[10,12]}',
      },
    ]);
  });
});

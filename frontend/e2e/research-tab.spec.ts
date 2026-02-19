import { expect, test } from '@playwright/test';

const E2E_SESSION_ID = 'sess-e2e-research';

const fulfillJson = async (route: any, payload: unknown) => {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  });
};

const buildDashboardPayload = (symbol = 'AAPL') => ({
  success: true,
  state: {
    active_asset: { symbol, type: 'equity', display_name: symbol },
    capabilities: {
      revenue_trend: true,
      segment_mix: true,
      sector_weights: true,
      top_constituents: true,
      holdings: true,
      market_chart: true,
    },
    watchlist: [
      { symbol: 'AAPL', type: 'equity', name: 'Apple' },
      { symbol: 'TSLA', type: 'equity', name: 'Tesla' },
    ],
    layout_prefs: { hidden_widgets: [], order: [] },
    news_mode: { mode: 'market' },
    debug: {},
  },
  data: {
    snapshot: { revenue: 100, eps: 3.2, gross_margin: 40, fcf: 10 },
    charts: {
      market_chart: [
        { time: Date.now() / 1000 - 86400, close: 180 },
        { time: Date.now() / 1000, close: 182 },
      ],
      revenue_trend: [],
      segment_mix: [],
    },
    news: { market: [], impact: [] },
  },
});

const buildReplayReport = (overrides: Record<string, unknown> = {}) => ({
  report_id: 'r-default',
  ticker: 'AAPL',
  title: 'AAPL 深度研究',
  summary: '研究摘要',
  sentiment: 'neutral',
  confidence_score: 0.72,
  grounding_rate: 0.82,
  generated_at: '2026-02-18T00:00:00Z',
  report_hints: {
    quality: {
      deep_report_required: true,
      qualified: true,
      missing_requirements: [],
    },
    grounding: {
      grounding_rate: 0.82,
      claim_count: 6,
      grounded_count: 5,
    },
  },
  risks: [],
  citations: [
    {
      source_id: 'src_1',
      source: 'Reuters',
      title: 'Reuters note',
      snippet: 'Sample evidence snippet.',
      url: 'https://example.com/reuters-note',
      published_date: '2026-02-17T00:00:00Z',
    },
  ],
  agent_status: {
    price_agent: { status: 'success', confidence: 0.8 },
    news_agent: { status: 'success', confidence: 0.7 },
    fundamental_agent: { status: 'success', confidence: 0.7 },
    technical_agent: { status: 'success', confidence: 0.7 },
    macro_agent: { status: 'success', confidence: 0.7 },
    risk_agent: { status: 'not_run', skipped_reason: 'policy gate' },
    deep_search_agent: { status: 'not_run', skipped_reason: 'analysis_depth=report' },
  },
  agent_diagnostics: {
    risk_agent: { status: 'not_run', fallback_reason: 'policy gate' },
  },
  meta: {
    source_trigger: 'dashboard_deep_search',
    graph_trace: {
      policy: {
        allowed_agents: [
          'price_agent',
          'news_agent',
          'fundamental_agent',
          'technical_agent',
          'macro_agent',
        ],
        agent_selection: {
          removed_by_prefs: ['risk_agent'],
          removed_by_analysis_depth: ['deep_search_agent'],
        },
      },
    },
    agent_summaries: [
      {
        agent_name: 'price_agent',
        raw_output: { as_of: '2026-02-18T00:00:00Z' },
      },
    ],
    grounding: { grounding_rate: 0.82 },
  },
  synthesis_report: '## 报告\n\n正文',
  ...overrides,
});

test.describe('Research tab regressions', () => {
  let replayReport: Record<string, unknown>;
  let reportId: string;

  test.beforeEach(async ({ page }) => {
    replayReport = buildReplayReport();
    reportId = 'r-default';

    await page.addInitScript((sessionId) => {
      localStorage.setItem('finsight-session-id', String(sessionId));
      localStorage.setItem(
        'fs_dashboard_active_v1',
        JSON.stringify({ symbol: 'AAPL', type: 'equity', display_name: 'Apple' }),
      );
      localStorage.setItem('fs_dashboard_layout_v1', JSON.stringify({ hidden_widgets: [], order: [] }));
      localStorage.setItem('fs_dashboard_news_mode_v1', JSON.stringify('market'));
    }, E2E_SESSION_ID);

    await page.route('**/api/dashboard**', async (route) => {
      const url = new URL(route.request().url());
      const symbol = url.searchParams.get('symbol') || 'AAPL';
      await fulfillJson(route, buildDashboardPayload(symbol));
    });
    await page.route('**/api/dashboard/insights**', async (route) => {
      await fulfillJson(route, {
        success: true,
        symbol: 'AAPL',
        insights: {
          overview: {
            agent_name: 'digest_agent',
            tab: 'overview',
            score: 5.5,
            score_label: '中性',
            summary: '综合评分中性，等待更多确认信号。',
            key_points: ['估值中性', '趋势尚未明确'],
            risks: ['短期波动风险'],
            key_metrics: [],
            confidence: 0.7,
            as_of: '2026-02-18T00:00:00Z',
            model_generated: true,
          },
          financial: {
            agent_name: 'digest_agent',
            tab: 'financial',
            score: 5.2,
            score_label: '中性',
            summary: '财务面中性。',
            key_points: [],
            risks: [],
            confidence: 0.7,
            as_of: '2026-02-18T00:00:00Z',
            model_generated: true,
          },
          technical: {
            agent_name: 'digest_agent',
            tab: 'technical',
            score: 5.1,
            score_label: '中性',
            summary: '技术面中性。',
            key_points: [],
            risks: [],
            confidence: 0.7,
            as_of: '2026-02-18T00:00:00Z',
            model_generated: true,
          },
          news: {
            agent_name: 'digest_agent',
            tab: 'news',
            score: 5.0,
            score_label: '中性',
            summary: '新闻面中性。',
            key_points: [],
            risks: [],
            confidence: 0.7,
            as_of: '2026-02-18T00:00:00Z',
            model_generated: true,
          },
          peers: {
            agent_name: 'digest_agent',
            tab: 'peers',
            score: 5.0,
            score_label: '中性',
            summary: '同行对比中性。',
            key_points: [],
            risks: [],
            confidence: 0.7,
            as_of: '2026-02-18T00:00:00Z',
            model_generated: true,
          },
        },
        cached: false,
        cache_age_seconds: 0,
        generated_at: '2026-02-18T00:00:00Z',
      });
    });
    await page.route('**/api/user/profile**', async (route) => {
      await fulfillJson(route, { profile: { name: 'E2E User', watchlist: ['AAPL', 'TSLA'] } });
    });
    await page.route('**/api/subscriptions**', async (route) => {
      await fulfillJson(route, { subscriptions: [] });
    });
    await page.route('**/api/stock/price/**', async (route) => {
      await fulfillJson(route, { success: true, data: { price: 180.5, change_percent: 1.2 } });
    });
    await page.route('**/api/reports/index**', async (route) => {
      await fulfillJson(route, {
        success: true,
        session_id: E2E_SESSION_ID,
        count: 1,
        items: [
          {
            report_id: reportId,
            ticker: 'AAPL',
            title: 'AAPL 深度报告',
            summary: 'summary',
            generated_at: '2026-02-18T00:00:00Z',
          },
        ],
      });
    });
    await page.route('**/api/reports/replay/**', async (route) => {
      const replay = {
        success: true,
        session_id: E2E_SESSION_ID,
        report: replayReport,
        citations: Array.isArray(replayReport.citations) ? replayReport.citations : [],
        trace_digest: {},
      };
      await fulfillJson(route, replay);
    });
    await page.route('**/health', async (route) => {
      await fulfillJson(route, { status: 'ok' });
    });
  });

  test('hard-blocks conclusions when report ticker mismatches active ticker', async ({ page }) => {
    reportId = 'r-mismatch';
    replayReport = buildReplayReport({
      report_id: reportId,
      ticker: 'GOOG',
      title: 'GOOG 深度研究',
    });

    await page.goto('/dashboard/AAPL?tab=research');

    await expect(page.getByTestId('research-ticker-mismatch')).toBeVisible();
    await expect(page.getByTestId('research-conclusion-disabled')).toBeVisible();
  });

  test('shows prominent grounding warning when grounding rate is low', async ({ page }) => {
    reportId = 'r-grounding-gap';
    replayReport = buildReplayReport({
      report_id: reportId,
      grounding_rate: 0.48,
      report_hints: {
        quality: {
          deep_report_required: true,
          qualified: false,
          missing_requirements: ['缺少可识别 10-K 引用'],
        },
        grounding: {
          grounding_rate: 0.48,
          claim_count: 10,
          grounded_count: 4,
        },
      },
      risks: ['证据溯源率偏低（48%），部分断言可能缺少直接证据支持'],
    });

    await page.goto('/dashboard/AAPL?tab=research');

    await expect(page.getByTestId('research-grounding-warning')).toBeVisible();
    await expect(page.getByTestId('research-empty-state')).toHaveAttribute('data-state', 'quality-gap');
  });

  test('shows diagnostic tooltip for agent execution diagnostics', async ({ page }) => {
    reportId = 'r-diagnostic';
    replayReport = buildReplayReport({
      report_id: reportId,
      risks: ['存在 1 项跨智能体数据冲突尚未裁决，结论可信度受限'],
      agent_status: {
        price_agent: { status: 'success', confidence: 0.8 },
        news_agent: { status: 'success', confidence: 0.7 },
        fundamental_agent: { status: 'success', confidence: 0.7 },
        technical_agent: { status: 'success', confidence: 0.7 },
        macro_agent: { status: 'success', confidence: 0.7 },
        risk_agent: { status: 'not_run', skipped_reason: 'policy gate' },
        deep_search_agent: { status: 'not_run', skipped_reason: 'analysis_depth=report' },
      },
    });

    await page.goto('/dashboard/AAPL');

    const diagnosticTip = page.getByTestId('agent-diagnostic-tip-0');
    await expect(diagnosticTip).toBeVisible();
    await diagnosticTip.hover();
    await expect(diagnosticTip.locator('[role="tooltip"]')).toBeVisible();
  });
});

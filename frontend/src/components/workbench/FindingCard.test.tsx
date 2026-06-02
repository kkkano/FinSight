import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  FindingCard,
  formatConfidence,
  isActionEnabled,
  resolveAgentLabel,
  resolveTriggerVisual,
} from './FindingCard';
import type { AgentAnalysis, Finding } from '../../types/monitor';

/** 把 JSX 渲染为压缩空白后的静态 HTML 字符串 */
const renderText = (node: React.ReactElement) =>
  renderToStaticMarkup(node).replace(/\s+/g, ' ');

/** 构造测试用 Finding */
function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: 'f-1',
    session_id: 's-1',
    created_at: new Date().toISOString(),
    target: 'TSLA',
    trigger_type: 'price_move',
    trigger_detail: { change_pct: -5.2, threshold: 5.0 },
    title: 'TSLA 单日下跌 5.2%',
    summary: '特斯拉今日大幅下挫，触发价格异动阈值。',
    agent_analysis: null,
    actions: [{ type: 'full_report', label: '看完整简报', ticker: 'TSLA' }],
    status: 'new',
    ...overrides,
  };
}

describe('resolveTriggerVisual', () => {
  it('marks downward price move as danger color', () => {
    const visual = resolveTriggerVisual('price_move', { change_pct: -5.2 });
    expect(visual.accentClass).toContain('fin-danger');
    expect(visual.label).toBe('价格异动');
  });

  it('marks upward price move as success color', () => {
    const visual = resolveTriggerVisual('price_move', { change_pct: 6.1 });
    expect(visual.accentClass).toContain('fin-success');
  });

  it('marks concentration as warning color', () => {
    const visual = resolveTriggerVisual('concentration', { concentration_pct: 85 });
    expect(visual.accentClass).toContain('fin-warning');
    expect(visual.label).toBe('集中度风险');
  });
});

describe('isActionEnabled', () => {
  it('enables only full_report in Phase 1', () => {
    expect(isActionEnabled('full_report')).toBe(true);
    expect(isActionEnabled('risk_review')).toBe(false);
    expect(isActionEnabled('rebalance')).toBe(false);
  });
});

describe('FindingCard', () => {
  it('renders a price_move finding with title, summary and action', () => {
    const text = renderText(<FindingCard finding={makeFinding()} />);
    expect(text).toContain('TSLA 单日下跌 5.2%');
    expect(text).toContain('特斯拉今日大幅下挫');
    expect(text).toContain('价格异动');
    expect(text).toContain('看完整简报');
  });

  it('renders a concentration finding', () => {
    const finding = makeFinding({
      trigger_type: 'concentration',
      target: 'PORTFOLIO',
      title: '科技板块集中度 85%',
      summary: '单一板块占比超过 80% 阈值。',
      trigger_detail: { concentration_pct: 85, threshold: 80 },
      actions: [{ type: 'rebalance', label: '调仓建议' }],
    });
    const text = renderText(<FindingCard finding={finding} />);
    expect(text).toContain('科技板块集中度 85%');
    expect(text).toContain('集中度风险');
    expect(text).toContain('调仓建议');
  });

  it('shows the new dot for unread findings', () => {
    const text = renderText(<FindingCard finding={makeFinding({ status: 'new' })} />);
    expect(text).toContain('finding-new-dot');
  });

  it('hides the new dot for viewed findings', () => {
    const text = renderText(<FindingCard finding={makeFinding({ status: 'viewed' })} />);
    expect(text).not.toContain('finding-new-dot');
  });

  it('disables non-full_report actions (Phase 2 gated)', () => {
    const finding = makeFinding({
      actions: [
        { type: 'full_report', label: '看完整简报', ticker: 'TSLA' },
        { type: 'risk_review', label: '风险评估' },
      ],
    });
    const html = renderToStaticMarkup(<FindingCard finding={finding} />);
    // 两个按钮都应渲染
    expect(html).toContain('data-testid="finding-action-full_report"');
    expect(html).toContain('data-testid="finding-action-risk_review"');
    // disabled 的 Phase 2 按钮：带 disabled 属性 + "Phase 2 开放" tooltip + cursor-not-allowed
    expect(html).toContain('title="Phase 2 开放"');
    expect(html).toContain('cursor-not-allowed');
    // 提取 risk_review 按钮片段，确认其带 disabled（属性顺序无关）
    const riskBtnMatch = html.match(/<button[^>]*finding-action-risk_review[^>]*>/);
    expect(riskBtnMatch?.[0] ?? '').toContain('disabled');
  });
});

// ── Phase 2: AI 分析区块 ──────────────────────────────────────

function makeAnalysis(overrides: Partial<AgentAnalysis> = {}): AgentAnalysis {
  return {
    agent: 'technical_agent',
    summary: 'TSLA 技术快照：均线呈空头排列，RSI 进入超卖区，短期存在技术性反弹空间。',
    confidence: 0.85,
    data_sources: ['kline', 'quote'],
    analyzed_at: new Date().toISOString(),
    ...overrides,
  };
}

describe('resolveAgentLabel', () => {
  it('maps agent ids to Chinese labels', () => {
    expect(resolveAgentLabel('technical_agent')).toBe('技术分析');
    expect(resolveAgentLabel('risk_agent')).toBe('风险评估');
    expect(resolveAgentLabel('unknown_agent')).toBe('unknown_agent');
  });
});

describe('formatConfidence', () => {
  it('formats fractional confidence as percentage', () => {
    expect(formatConfidence(0.85)).toBe('85%');
  });

  it('passes through integer-scale confidence', () => {
    expect(formatConfidence(75)).toBe('75%');
  });

  it('returns 未评估 for null (honest principle, no fabrication)', () => {
    expect(formatConfidence(null)).toBe('未评估');
  });
});

describe('FindingCard agent_analysis (Phase 2)', () => {
  it('renders the AI analysis block when agent_analysis exists', () => {
    const finding = makeFinding({ agent_analysis: makeAnalysis() });
    const html = renderToStaticMarkup(<FindingCard finding={finding} />);
    expect(html).toContain('data-testid="finding-agent-analysis"');
    expect(html).toContain('AI 分析');
    expect(html).toContain('技术分析');
    expect(html).toContain('置信度 85%');
    // 数据来源 tag
    expect(html).toContain('data-testid="finding-agent-source"');
    expect(html).toContain('kline');
  });

  it('shows 未评估 when confidence is null', () => {
    const finding = makeFinding({ agent_analysis: makeAnalysis({ confidence: null }) });
    const html = renderToStaticMarkup(<FindingCard finding={finding} />);
    expect(html).toContain('置信度 未评估');
  });

  it('does not render the analysis block when agent_analysis is null (Phase 1 unchanged)', () => {
    const html = renderToStaticMarkup(<FindingCard finding={makeFinding({ agent_analysis: null })} />);
    expect(html).not.toContain('data-testid="finding-agent-analysis"');
    expect(html).not.toContain('AI 分析');
  });

  it('renders risk_agent analysis with the correct label', () => {
    const finding = makeFinding({
      trigger_type: 'concentration',
      target: 'PORTFOLIO',
      agent_analysis: makeAnalysis({ agent: 'risk_agent', summary: 'NVDA 风险评分 70/100。' }),
    });
    const html = renderToStaticMarkup(<FindingCard finding={finding} />);
    expect(html).toContain('风险评估');
    expect(html).toContain('NVDA 风险评分');
  });
});

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  FindingCard,
  formatConfidence,
  isActionEnabled,
  resolveActionTarget,
  resolveAgentLabel,
  resolveSessionBadge,
  resolveTriggerVisual,
} from './FindingCard';
import { extractMarketSession } from '../../types/monitor';
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

  it('marks sentiment_shift with purple (fin-primary) + 舆情突变 badge', () => {
    const visual = resolveTriggerVisual('sentiment_shift', { score: -0.52 });
    expect(visual.accentClass).toContain('fin-primary');
    expect(visual.label).toBe('舆情突变');
  });

  it('marks earnings_near with amber + 财报临近 badge', () => {
    const visual = resolveTriggerVisual('earnings_near', { earnings_date: '2026-06-15' });
    expect(visual.accentClass).toContain('amber');
    expect(visual.label).toBe('财报临近');
  });

  it('marks macro_event with sky blue + 宏观事件 badge', () => {
    const visual = resolveTriggerVisual('macro_event', { events: ['CPI release'] });
    expect(visual.accentClass).toContain('sky');
    expect(visual.label).toBe('宏观事件');
  });
});

describe('isActionEnabled', () => {
  it('enables full_report and rebalance; others remain Phase 2 gated', () => {
    expect(isActionEnabled('full_report')).toBe(true);
    expect(isActionEnabled('rebalance')).toBe(true);
    expect(isActionEnabled('risk_review')).toBe(false);
    expect(isActionEnabled('chart')).toBe(false);
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

// ── 三种新发现类型渲染（舆情突变 / 财报临近 / 宏观事件） ────────────

describe('FindingCard new trigger types', () => {
  it('renders a sentiment_shift finding with 舆情突变 badge', () => {
    const finding = makeFinding({
      trigger_type: 'sentiment_shift',
      target: 'AAPL',
      title: 'AAPL 舆情强负面：分数 -0.52',
      summary: '苹果近期舆情急转直下，负面情绪集中爆发。',
      trigger_detail: { score: -0.52 },
      actions: [{ type: 'full_report', label: '看完整简报', ticker: 'AAPL' }],
    });
    const text = renderText(<FindingCard finding={finding} />);
    expect(text).toContain('AAPL 舆情强负面：分数 -0.52');
    expect(text).toContain('舆情突变');
  });

  it('renders an earnings_near finding with 财报临近 badge', () => {
    const finding = makeFinding({
      trigger_type: 'earnings_near',
      target: 'AAPL',
      title: 'AAPL 财报临近：2026-06-15',
      summary: '苹果将于 2026-06-15 公布财报，提前关注预期。',
      trigger_detail: { earnings_date: '2026-06-15' },
      actions: [{ type: 'full_report', label: '看完整简报', ticker: 'AAPL' }],
    });
    const text = renderText(<FindingCard finding={finding} />);
    expect(text).toContain('AAPL 财报临近：2026-06-15');
    expect(text).toContain('财报临近');
  });

  it('renders a macro_event finding (target=MACRO) with 宏观事件 badge', () => {
    const finding = makeFinding({
      trigger_type: 'macro_event',
      target: 'MACRO',
      title: '宏观事件临近：CPI release',
      summary: 'CPI 数据即将公布，可能放大市场波动。',
      trigger_detail: { events: ['CPI release'] },
      actions: [{ type: 'full_report', label: '看完整简报' }],
    });
    const text = renderText(<FindingCard finding={finding} />);
    expect(text).toContain('宏观事件临近：CPI release');
    expect(text).toContain('宏观事件');
  });
});

// ── 调仓建议按钮闭环 ───────────────────────────────────────────

describe('FindingCard rebalance action', () => {
  function makeRebalanceFinding() {
    return makeFinding({
      trigger_type: 'concentration',
      target: 'PORTFOLIO',
      title: '科技板块集中度 85%',
      summary: '单一板块占比超过 80% 阈值，建议调仓分散风险。',
      trigger_detail: { concentration_pct: 85, threshold: 80 },
      actions: [{ type: 'rebalance', label: '调仓建议' }],
    });
  }

  it('renders the rebalance button enabled (no longer disabled / Phase 2 gated)', () => {
    const html = renderToStaticMarkup(<FindingCard finding={makeRebalanceFinding()} />);
    expect(html).toContain('data-testid="finding-action-rebalance"');
    // 提取 rebalance 按钮片段，确认不含 disabled
    const btnMatch = html.match(/<button[^>]*finding-action-rebalance[^>]*>/);
    expect(btnMatch?.[0] ?? '').not.toContain('disabled');
    // tooltip 应为真实 label，而非 "Phase 2 开放"
    expect(btnMatch?.[0] ?? '').toContain('title="调仓建议"');
  });

  it('routes rebalance action to the rebalance target (real resolveActionTarget)', () => {
    // 验证组件实际使用的派发函数：rebalance → { kind: 'rebalance' }
    const finding = makeRebalanceFinding();
    const target = resolveActionTarget(finding.actions[0], finding.target);
    expect(target).toEqual({ kind: 'rebalance' });
  });

  it('routes full_report action to chat with the resolved ticker', () => {
    const target = resolveActionTarget(
      { type: 'full_report', label: '看完整简报', ticker: 'AAPL' },
      'AAPL',
    );
    expect(target).toEqual({ kind: 'chat', ticker: 'AAPL' });
  });

  it('routes PORTFOLIO-level full_report (no ticker) to none', () => {
    const target = resolveActionTarget(
      { type: 'full_report', label: '看完整简报' },
      'PORTFOLIO',
    );
    expect(target).toEqual({ kind: 'none' });
  });

  it('routes Phase 2 gated actions to none', () => {
    const target = resolveActionTarget({ type: 'risk_review', label: '风险评估' }, 'TSLA');
    expect(target).toEqual({ kind: 'none' });
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

  it('maps the three new agent ids (news / deep_search / macro)', () => {
    expect(resolveAgentLabel('news_agent')).toBe('舆情分析');
    expect(resolveAgentLabel('deep_search_agent')).toBe('深度研究');
    expect(resolveAgentLabel('macro_agent')).toBe('宏观分析');
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

// ── 交易时段标注（盘前/盘后 badge） ──────────────────────────────

describe('extractMarketSession', () => {
  it('extracts a valid session string', () => {
    expect(extractMarketSession({ market_session: 'pre_market' })).toBe('pre_market');
    expect(extractMarketSession({ market_session: 'after_hours' })).toBe('after_hours');
    expect(extractMarketSession({ market_session: 'regular' })).toBe('regular');
    expect(extractMarketSession({ market_session: 'closed' })).toBe('closed');
  });

  it('returns null when the field is missing', () => {
    expect(extractMarketSession({ change_pct: -5.2 })).toBeNull();
  });

  it('returns null for invalid values (number / garbage string)', () => {
    expect(extractMarketSession({ market_session: 42 })).toBeNull();
    expect(extractMarketSession({ market_session: 'lunch_break' })).toBeNull();
    expect(extractMarketSession({ market_session: '' })).toBeNull();
  });
});

describe('resolveSessionBadge', () => {
  it('returns an orange 盘前 badge for pre_market', () => {
    const badge = resolveSessionBadge('pre_market');
    expect(badge?.label).toBe('盘前');
    expect(badge?.className).toContain('orange');
  });

  it('returns an indigo 盘后 badge for after_hours', () => {
    const badge = resolveSessionBadge('after_hours');
    expect(badge?.label).toBe('盘后');
    expect(badge?.className).toContain('indigo');
  });

  it('returns null for regular / closed / null (盘中为常态不标注)', () => {
    expect(resolveSessionBadge('regular')).toBeNull();
    expect(resolveSessionBadge('closed')).toBeNull();
    expect(resolveSessionBadge(null)).toBeNull();
  });
});

describe('FindingCard market session badge', () => {
  it('renders the 盘前 badge when market_session=pre_market', () => {
    const finding = makeFinding({
      target: 'NVDA',
      title: 'NVDA 盘前下跌 5.2%',
      trigger_detail: { change_pct: -5.2, threshold: 5.0, market_session: 'pre_market' },
    });
    const html = renderToStaticMarkup(<FindingCard finding={finding} />);
    expect(html).toContain('data-testid="finding-session-badge"');
    expect(html).toContain('盘前');
  });

  it('renders the 盘后 badge when market_session=after_hours', () => {
    const finding = makeFinding({
      target: 'NVDA',
      title: 'NVDA 盘后下跌 5.2%',
      trigger_detail: { change_pct: -5.2, threshold: 5.0, market_session: 'after_hours' },
    });
    const html = renderToStaticMarkup(<FindingCard finding={finding} />);
    expect(html).toContain('data-testid="finding-session-badge"');
    expect(html).toContain('盘后');
  });

  it('does not render a session badge for market_session=regular', () => {
    const finding = makeFinding({
      trigger_detail: { change_pct: -5.2, threshold: 5.0, market_session: 'regular' },
    });
    const html = renderToStaticMarkup(<FindingCard finding={finding} />);
    expect(html).not.toContain('data-testid="finding-session-badge"');
  });

  it('does not render a session badge when market_session is missing', () => {
    const finding = makeFinding({
      trigger_detail: { change_pct: -5.2, threshold: 5.0 },
    });
    const html = renderToStaticMarkup(<FindingCard finding={finding} />);
    expect(html).not.toContain('data-testid="finding-session-badge"');
  });
});

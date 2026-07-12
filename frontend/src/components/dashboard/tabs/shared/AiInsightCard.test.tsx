import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { InsightCard } from '../../../../types/dashboard';
import { sanitizeOverrideQuestion } from '../../../../utils/dashboardDeepDiveOverlay';
import { AiInsightCard } from './AiInsightCard';
import { confidenceColorClass, formatAsOf } from './aiInsightFormat';

const baseInsight: InsightCard = {
  agent_name: 'technical_digest',
  scorer_name: 'technical_scorer',
  analyst: {
    key: 'technical_agent',
    name_zh: '技术面分析师',
    short_zh: '技术面',
    glyph: 'T',
    color_token: 't-predict',
    mandate_zh: 'RSI、MACD、均线、形态与交易信号研判',
  },
  tab: 'technical',
  score: 6.4,
  score_label: '中性',
  summary: 'RSI 55，趋势信号混合。',
  key_points: ['RSI 处于中性区间'],
  risks: ['上方阻力仍需确认'],
  key_metrics: [
    { label: 'RSI', value: '55' },
    { label: 'MACD', value: '0.18' },
  ],
  confidence: 0.8,
  as_of: '2026-05-31T00:00:00+00:00',
  model_generated: true,
};

describe('AiInsightCard honesty labels', () => {
  it('把仪表盘打分诚实标注为「快速评分」而非自主 Agent', () => {
    const html = renderToStaticMarkup(
      <AiInsightCard tab="technical" insight={baseInsight} />,
    );

    // 快速评分与深挖使用同一个 AgentProfile 人格。
    expect(html).toContain('AI 技术分析');
    expect(html).toContain('技术面分析师');
    expect(html).toContain('data-testid="insight-analyst"');
    // 诚实标签：快速评分（model_generated=true）
    expect(html).toContain('快速评分');
    expect(html).toContain('AI 评分 · 基于 2 项真实指标 · 置信度 80%');
    // 不得伪装成自主 Agent
    expect(html).not.toContain('Digest Agent');
    expect(html).not.toContain('AI Agent');
  });

  it('提供 onDeepDive 回调时使用同一分析师署名引导深度分析', () => {
    const html = renderToStaticMarkup(
      <AiInsightCard
        tab="technical"
        insight={baseInsight}
        onDeepDive={() => {}}
      />,
    );

    expect(html).toContain('请技术面分析师深入分析 →');
  });
});

describe('深挖按钮事件对象防御（修复 Converting circular structure to JSON）', () => {
  it('sanitizeOverrideQuestion：事件对象/DOM 元素等非字符串一律清洗为 null', () => {
    // 模拟 React MouseEvent（带循环引用的对象，JSON.stringify 会崩）
    const fakeEvent: Record<string, unknown> = { type: 'click' };
    fakeEvent.target = { ownerEvent: fakeEvent };

    expect(sanitizeOverrideQuestion(fakeEvent)).toBeNull();
    expect(sanitizeOverrideQuestion(undefined)).toBeNull();
    expect(sanitizeOverrideQuestion(null)).toBeNull();
    expect(sanitizeOverrideQuestion(123)).toBeNull();
    expect(sanitizeOverrideQuestion('')).toBeNull();
    expect(sanitizeOverrideQuestion('   ')).toBeNull();
  });

  it('sanitizeOverrideQuestion：合法字符串原样保留', () => {
    expect(sanitizeOverrideQuestion('为什么今天大涨？')).toBe('为什么今天大涨？');
  });
});

describe('AiInsightCard confidence & as_of visibility (P2-4)', () => {
  it('在 Footer 直接展示置信度百分比与数据时点', () => {
    const html = renderToStaticMarkup(
      <AiInsightCard tab="technical" insight={baseInsight} />,
    );

    expect(html).toContain('置信度 80%');
    expect(html).toContain('数据时点');
  });

  it('置信度颜色编码：高绿 / 中黄 / 低红', () => {
    expect(confidenceColorClass(0.9)).toBe('text-fin-success');
    expect(confidenceColorClass(0.6)).toBe('text-fin-warning');
    expect(confidenceColorClass(0.3)).toBe('text-fin-danger');
  });

  it('formatAsOf 输出短格式时间，无效输入返回空字符串', () => {
    expect(formatAsOf('2026-05-31T08:15:00+00:00')).toMatch(/^\d{2}-\d{2} \d{2}:\d{2}$/);
    expect(formatAsOf('not-a-date')).toBe('');
    expect(formatAsOf('')).toBe('');
  });
});

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { InsightCard } from '../../../../types/dashboard';
import { AiInsightCard, confidenceColorClass, formatAsOf } from './AiInsightCard';

const baseInsight: InsightCard = {
  agent_name: 'technical_digest',
  scorer_name: 'technical_scorer',
  tab: 'technical',
  score: 6.4,
  score_label: '中性',
  summary: 'RSI 55，趋势信号混合。',
  key_points: ['RSI 处于中性区间'],
  risks: ['上方阻力仍需确认'],
  confidence: 0.8,
  as_of: '2026-05-31T00:00:00+00:00',
  model_generated: true,
};

describe('AiInsightCard honesty labels', () => {
  it('把仪表盘打分诚实标注为「快速评分」而非自主 Agent', () => {
    const html = renderToStaticMarkup(
      <AiInsightCard tab="technical" insight={baseInsight} />,
    );

    // 标题用 Tab 维度名，不冒充某个 Agent
    expect(html).toContain('AI 技术分析');
    // 诚实标签：快速评分（model_generated=true）
    expect(html).toContain('快速评分');
    // 不得伪装成自主 Agent
    expect(html).not.toContain('Digest Agent');
    expect(html).not.toContain('AI Agent');
  });

  it('提供 onDeepDive 回调时渲染「深挖」入口引导真正的 Agent 深度分析', () => {
    const html = renderToStaticMarkup(
      <AiInsightCard
        tab="technical"
        insight={baseInsight}
        onDeepDive={() => {}}
      />,
    );

    expect(html).toContain('深挖');
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

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { InsightCard } from '../../../../types/dashboard';
import { AiInsightCard } from './AiInsightCard';

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

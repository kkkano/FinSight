import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import type { MorningBriefData } from '../../api/client';
import { MorningBriefCard } from './MorningBriefCard';

function buildBrief(): MorningBriefData {
  return {
    date: '2026-07-11',
    summary: '今日跟踪 1 只标的。',
    highlights: [{
      ticker: 'AAPL',
      price: 210,
      price_change: 2,
      price_change_pct: 0.96,
      trend: 'neutral',
      key_event: '新品发布',
      analyst: {
        name: 'news_agent',
        display_name: '新闻分析师',
        short_zh: '新闻',
        glyph: 'N',
        color_token: 't-warn',
      },
    }],
    market_mood: 'neutral',
    market_mood_cn: '中性',
    action_items: [],
  };
}

describe('MorningBriefCard', () => {
  it('仅在要点携带真实 analyst 元数据时显示 short_zh chip', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <MorningBriefCard brief={buildBrief()} loading={false} error={null} onGenerate={() => {}} />
      </MemoryRouter>,
    );
    expect(html).toContain('data-testid="morning-brief-analyst-AAPL"');
    expect(html).toContain('N');
    expect(html).toContain('新闻');
  });

  it('确定性聚合要点不伪造 Agent 署名', () => {
    const brief = buildBrief();
    delete brief.highlights[0].analyst;
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <MorningBriefCard brief={brief} loading={false} error={null} onGenerate={() => {}} />
      </MemoryRouter>,
    );
    expect(html).not.toContain('morning-brief-analyst-AAPL');
  });
});

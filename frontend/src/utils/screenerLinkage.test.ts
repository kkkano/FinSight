import { describe, expect, it } from 'vitest';

import { buildScreenerAskAiPrompt, buildScreenerFilterSummary } from './screenerLinkage';

describe('screener linkage', () => {
  it('describes the active market and optional sector filter', () => {
    expect(buildScreenerFilterSummary('US', 'Technology')).toBe('市场=US，行业=Technology');
    expect(buildScreenerFilterSummary('cn', '')).toBe('市场=CN');
  });

  it('builds the row ask-AI prompt from ticker and current filters', () => {
    expect(buildScreenerAskAiPrompt('aapl', '市场=US，行业=Technology'))
      .toBe('分析一下 AAPL，它在筛选条件“市场=US，行业=Technology”下入选');
  });
});

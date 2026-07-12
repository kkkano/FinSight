import { describe, expect, it } from 'vitest';

import { buildMorningBriefDeepDiveHref, buildMorningBriefDeepDivePrompt } from './morningBriefLinkage';

describe('morning brief linkage', () => {
  it('includes the related ticker when a highlight has one', () => {
    expect(buildMorningBriefDeepDivePrompt('财报后指引上调。', 'aapl'))
      .toBe('晨报提到：财报后指引上调。展开讲讲对 AAPL 的影响。');
  });

  it('keeps action items useful without inventing a ticker', () => {
    const href = buildMorningBriefDeepDiveHref('降低高波动仓位');
    const prompt = new URLSearchParams(href.split('?')[1]).get('prompt');
    expect(prompt).toBe('晨报提到：降低高波动仓位。展开讲讲它的影响和应对。');
  });
});

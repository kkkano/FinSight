import { describe, expect, it } from 'vitest';

import { buildDashboardAskAiDraft, getDashboardTabLabel } from './dashboardAskAi';

describe('Dashboard ask-AI linkage', () => {
  it('prefills the current symbol and active tab label', () => {
    expect(buildDashboardAskAiDraft('aapl', 'technical')).toBe('关于 AAPL 的技术面，');
    expect(buildDashboardAskAiDraft('NVDA', 'research')).toBe('关于 NVDA 的深度研究，');
    expect(getDashboardTabLabel('unknown')).toBe('综合分析');
  });
});

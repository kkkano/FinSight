import { describe, expect, it } from 'vitest';
import { dashboardResearchContext } from './dashboardResearchContext';

describe('dashboard research handoff context', () => {
  it('carries only selected metric, declared time range and existing references', () => {
    const context = dashboardResearchContext({ as_of: '2026-11-11T12:00:00Z',
      time_range: { start: '2026-10-01', end: '2026-10-31', period: '1mo' },
      data_refs: ['known-dataset', 'known-dataset'], data_ref: 'known-table', api_key: 'private-key' },
    { id: 'market_cap', label: '总市值', value: 123, unit: 'USD' });
    expect(context).toEqual({ selectedMetric: { id: 'market_cap', label: '总市值', value: 123, unit: 'USD' },
      timeRange: { start: '2026-10-01', end: '2026-10-31', period: '1mo' }, dataRefs: ['known-dataset', 'known-table'] });
    expect(JSON.stringify(context)).not.toContain('private-key');
    expect(dashboardResearchContext(undefined).dataRefs).toEqual([]);
  });
});

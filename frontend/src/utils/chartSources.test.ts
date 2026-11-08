import { describe, expect, it } from 'vitest';
import { chartSources, formatChartTimestamp } from './chartSources';

describe('chart source provenance', () => {
  it('counts duplicate provider records once and excludes tool/derived wrappers without changing evidence', () => {
    const evidence = [
      { source_id: 'tool', source: 'get_stock_historical_data', title: 'get_stock_historical_data output' },
      { source_id: 'one', source: 'twelve_data', as_of: '2026-11-06T00:00:00Z' },
      { source_id: 'two', source: 'Twelve Data', as_of: '2026-11-06T00:00:00Z' },
      { source_id: 'derived', source: 'analyze_dataset', url: 'https://example.com/calculation' },
    ];
    const before = JSON.stringify(evidence);
    expect(chartSources(evidence.map((source) => source.source_id), evidence)).toEqual([
      { name: 'Twelve Data', provider: 'Twelve Data', url: undefined, timestamps: ['2026-11-06'] },
    ]);
    expect(JSON.stringify(evidence)).toBe(before);
  });
  it('deduplicates traceable URLs and does not count the same provider-only projection again', () => {
    const evidence = [
      { source_id: 'one', source: 'reuters', url: 'https://example.com/article#first' },
      { source_id: 'duplicate', source: 'reuters', url: 'https://example.com/article#second' },
      { source_id: 'provider', source: 'reuters' },
      { source_id: 'other', source: 'reuters', url: 'https://example.com/another' },
    ];
    expect(chartSources(evidence.map((source) => source.source_id), evidence)).toHaveLength(2);
    expect(chartSources(['one'], evidence)).toHaveLength(1);
  });
  it('does not infer a data provider from an arbitrary title or internal placeholder', () => {
    expect(chartSources(['one', 'two'], [{ source_id: 'one', title: '某次计算结果' }, { source_id: 'two', source: 'market_chart' }])).toEqual([]);
  });
  it('formats declared timestamps without filling unknown dates or converting source time zones', () => {
    expect(formatChartTimestamp('2026-11-06T00:00:00Z')).toBe('2026-11-06');
    expect(formatChartTimestamp('2026-11-06T20:30:45Z')).toBe('2026-11-06 20:30:45 UTC');
    expect(formatChartTimestamp('2026-11-06T08:30:00+08:00')).toBe('2026-11-06 08:30:00 UTC+08:00');
    expect(formatChartTimestamp(null)).toBe('');
    expect(formatChartTimestamp('unknown')).toBe('');
  });
});

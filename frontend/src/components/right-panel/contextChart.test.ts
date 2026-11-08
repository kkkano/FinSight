import { describe, expect, it } from 'vitest';
import { buildContextChart, movingAverage20 } from './contextChart';

const rows = Array.from({ length: 22 }, (_, index) => ({ time: `2026-10-${String(index + 1).padStart(2, '0')}`,
  open: 100 + index, close: 101 + index, low: 99 + index, high: 102 + index, volume: 10000 + index }));

describe('context panel chart', () => {
  it('shows a true 20-day average and volume with inside zoom only', () => {
    expect(movingAverage20(rows)[18]).toBeNull();
    expect(movingAverage20(rows)[19]).toBe(110.5);
    const option = buildContextChart(rows, { line: false, dark: false, convention: 'intl' })!;
    expect(option.dataZoom).toEqual([{ type: 'inside', xAxisIndex: [0, 1], filterMode: 'none' }]);
    expect(option.series).toHaveLength(3);
    expect(JSON.stringify(option)).not.toContain('markLine');
  });
  it('draws only supplied verified price levels and real dates in the visible series', () => {
    const option = buildContextChart(rows, { line: true, dark: true, convention: 'cn',
      priceLevels: [{ price: 110, label: '评估价位', source_block_id: 'answer', ticker: 'AAPL' }],
      earningsDates: ['2026-10-10', '2030-01-01'] })!;
    const serialized = JSON.stringify(option);
    expect(serialized).toContain('110 评估价位');
    expect(serialized).toContain('2026-10-10');
    expect(serialized).not.toContain('2030-01-01');
    expect(buildContextChart([], { line: false, dark: false, convention: 'intl' })).toBeNull();
  });
});

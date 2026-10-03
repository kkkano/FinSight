import { describe, expect, it } from 'vitest';
import type { SmartChartData } from '../SmartChart';
import { selectChartRange } from './chartRange';

function series(labels: string[]): SmartChartData {
  return {
    labels,
    values: labels.map((_, index) => 100 + index),
    ohlc: labels.map((_, index) => [100 + index, 101 + index, 99 + index, 102 + index]),
    volume: labels.map((_, index) => 1000 + index),
  };
}

describe('selectChartRange', () => {
  it('一年周期裁掉供应商额外返回的旧数据并保留真实十二个月', () => {
    const data = series(['2025-04-17', '2025-10-01', '2025-10-02', '2026-09-30', '2026-10-02']);
    const selected = selectChartRange(data, '1y');
    expect(selected.labels).toEqual(['2025-10-02', '2026-09-30', '2026-10-02']);
    expect(selected.values).toEqual([102, 103, 104]);
    expect(selected.volume).toEqual([1002, 1003, 1004]);
    expect(data.labels).toHaveLength(5);
  });
  it('从末个真实交易日回看且保持价格、OHLC和成交量对齐', () => {
    const data = series(['2026-06-30', '2026-07-01', '2026-07-02', '2026-09-30', '2026-10-02']);
    const selected = selectChartRange(data, '3m');
    expect(selected.labels).toEqual(['2026-07-02', '2026-09-30', '2026-10-02']);
    expect(selected.values).toEqual([102, 103, 104]);
    expect(selected.ohlc).toEqual(data.ohlc?.slice(2));
    expect(selected.volume).toEqual([1002, 1003, 1004]);
    expect(data.labels).toHaveLength(5);
  });

  it('月末回看落在二月实际月末，兼容闰年', () => {
    expect(selectChartRange(series(['2024-02-28', '2024-02-29', '2024-03-31']), '1m').labels).toEqual(['2024-02-29', '2024-03-31']);
    expect(selectChartRange(series(['2026-02-27', '2026-02-28', '2026-03-31']), '1m').labels).toEqual(['2026-02-28', '2026-03-31']);
  });

  it('跨年、不足一个区间和一年范围不合成行情', () => {
    expect(selectChartRange(series(['2025-11-15', '2025-12-15', '2026-01-15']), '1m').labels).toEqual(['2025-12-15', '2026-01-15']);
    const short = series(['2026-10-01', '2026-10-02']);
    expect(selectChartRange(short, '6m')).toBe(short);
    expect(selectChartRange(short, '1y')).toBe(short);
    expect(selectChartRange(series([]), '3m').labels).toEqual([]);
  });
});

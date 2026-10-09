import { describe, expect, it } from 'vitest';
import { extractMetrics } from './ReportUtils';
import type { ReportSection } from '../../types';

describe('报告指标只读取结构化核验结果', () => {
  it('不把旧正文、时间或任意表格首行猜成指标', () => {
    const sections: ReportSection[] = [{ title: '正文', order: 1, contents: [
      { type: 'text', content: '市值：2,097.57 亿 USD\n源数据时间：2026-10-02T00:00:00Z\nEPS：30 天前 2.8881' },
      { type: 'table', content: { headers: ['日期', '金额'], rows: [['2026-10-02', '100 USD']] } },
    ] }];
    expect(extractMetrics(sections)).toEqual([]);
  });
  it('完整保留显式指标块的单位和期间', () => {
    const sections: ReportSection[] = [{ title: '指标', order: 1, contents: [
      { type: 'table', metadata: { kind: 'verified_metrics' }, content: {
        rows: [['市值', '2,097.57 亿 USD'], ['观测时间', '2026-10-02T00:00:00Z']],
      } },
    ] }];
    expect(extractMetrics(sections)).toEqual([
      { label: '市值', value: '2,097.57 亿 USD' }, { label: '观测时间', value: '2026-10-02T00:00:00Z' },
    ]);
  });
});

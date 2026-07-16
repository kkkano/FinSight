import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { ReportIR } from '../../types';
import { ToastProvider } from '../ui';
import { ReportView } from './ReportView';

const report: ReportIR = {
  report_id: 'rpt-share-test',
  ticker: 'AAPL',
  company_name: 'Apple',
  title: 'AAPL 研究报告',
  summary: '只读分享测试摘要',
  sentiment: 'bullish',
  confidence_score: 0.88,
  generated_at: '2026-07-12T00:00:00Z',
  sections: [],
  citations: [],
};

const renderReport = (readOnly: boolean) => renderToStaticMarkup(
  <ToastProvider>
    <ReportView report={report} readOnly={readOnly} />
  </ToastProvider>,
);

describe('ReportView 只读分享态', () => {
  it('隐藏实时行情与全部业务操作', () => {
    const html = renderReport(true);

    expect(html).toContain('AAPL');
    expect(html).not.toContain('全屏查看报告');
    expect(html).not.toContain('Export PDF');
    expect(html).not.toContain('Save to Watchlist');
    expect(html).not.toContain('Subscribe Alerts');
    expect(html).not.toContain('分享链接');
  });

  it('普通报告保留分享入口', () => {
    const html = renderReport(false);

    expect(html).toContain('分享链接');
    expect(html).not.toContain('Export PDF');
  });
});

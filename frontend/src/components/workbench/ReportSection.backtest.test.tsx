import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { ReportSection } from './ReportSection';

describe('ReportSection 报告回测联动', () => {
  it('为历史报告提供回测此观点入口', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ReportSection
          reports={[{
            report_id: 'rpt-1',
            session_id: 'session-1',
            ticker: 'AAPL',
            title: 'Apple research',
            generated_at: new Date().toISOString(),
          }]}
          loading={false}
        />
      </MemoryRouter>,
    );

    expect(html).toContain('回测此观点');
    expect(html).toContain('workbench-report-backtest-rpt-1');
  });
});

import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { ReportSection } from './ReportSection';

describe('ReportSection 报告行动入口', () => {
  it('为历史报告提供继续追问与回测入口', () => {
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
    expect(html).toContain('继续追问');
    expect(html).toContain('workbench-report-follow-up-rpt-1');

    const anchor = html.match(/<a[^>]*data-testid="workbench-report-follow-up-rpt-1"[^>]*>/)?.[0];
    const href = anchor?.match(/href="([^"]+)"/)?.[1];
    expect(href).toBeTruthy();
    const params = new URLSearchParams(String(href).split('?')[1].replaceAll('&amp;', '&'));
    expect(params.get('prompt')).toBe('基于报告《Apple research》，');
  });
});

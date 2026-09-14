import { describe, expect, it } from 'vitest';

import {
  buildReportFollowUpHref,
  buildReportFollowUpPrompt,
  buildHistoryReportHref,
} from './reportLinkage';

describe('report linkage', () => {
  it('builds a shareable history deep link from report_id', () => {
    expect(buildHistoryReportHref('lg/a 1')).toBe('/history?report=lg%2Fa%201');
  });

  it('builds a URL-backed follow-up draft from the report title', () => {
    expect(buildReportFollowUpPrompt('Apple 深度研究', 'lg-1')).toBe('基于报告《Apple 深度研究》，');

    const href = buildReportFollowUpHref('Apple 深度研究', 'lg-1');
    const params = new URLSearchParams(href.split('?')[1]);
    expect(params.get('prompt')).toBe('基于报告《Apple 深度研究》，');
  });
});

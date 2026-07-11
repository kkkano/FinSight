import { describe, expect, it } from 'vitest';

import {
  buildReportFollowUpHref,
  buildReportFollowUpPrompt,
  buildWorkbenchReportHref,
} from './reportLinkage';

describe('report linkage', () => {
  it('builds a shareable workbench deep link from report_id', () => {
    expect(buildWorkbenchReportHref('lg/a 1')).toBe('/workbench?report=lg%2Fa%201');
  });

  it('builds a URL-backed follow-up draft from the report title', () => {
    expect(buildReportFollowUpPrompt('Apple 深度研究', 'lg-1')).toBe('基于报告《Apple 深度研究》，');

    const href = buildReportFollowUpHref('Apple 深度研究', 'lg-1');
    const params = new URLSearchParams(href.split('?')[1]);
    expect(params.get('prompt')).toBe('基于报告《Apple 深度研究》，');
  });
});

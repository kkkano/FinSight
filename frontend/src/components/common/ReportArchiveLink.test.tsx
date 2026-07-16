import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { ReportArchiveLink } from './ReportArchiveLink';

describe('ReportArchiveLink', () => {
  it('links a completed report message to its history archive', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ReportArchiveLink reportId="lg-123" />
      </MemoryRouter>,
    );

    expect(html).toContain('已归档 · 在历史中查看 →');
    expect(html).toContain('href="/history?report=lg-123"');
  });
});

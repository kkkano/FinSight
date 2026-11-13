import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ReportIR } from '../types';
import { SharedReportHeader } from './SharedReportPage';

describe('shared report facts', () => {
  const report = { title: '已分享研究', generated_at: '2025-01-01T00:00:00Z', citations: [
    { source_id: 'S1', url: 'https://example.com/1' }, { source_id: 'S1', url: 'https://example.com/1' },
    { source_id: 'S2', url: 'https://example.com/2' },
  ] } as ReportIR;
  it('shows title, real publication time, source count and read-only label', () => {
    const markup = renderToStaticMarkup(<SharedReportHeader report={report} publishedAt="2026-11-11T01:00:00Z" />);
    expect(markup).toContain('已分享研究'); expect(markup).toContain('2026');
    expect(markup).toContain('2 个来源'); expect(markup).toContain('只读');
    expect(markup).not.toContain('2025'); expect(markup).not.toContain('分享时的');
  });
  it('does not substitute report creation time when publication time is missing', () => {
    const markup = renderToStaticMarkup(<SharedReportHeader report={report} />);
    expect(markup).toContain('发布时间未注明'); expect(markup).not.toContain('2025');
  });
});

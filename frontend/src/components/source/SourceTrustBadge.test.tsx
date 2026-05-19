import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { resolveSourceTrustBadge, SourceTrustBadge } from './SourceTrustBadge';

describe('resolveSourceTrustBadge', () => {
  it('prioritizes degraded sources over backing type', () => {
    expect(resolveSourceTrustBadge({ sourceType: 'report', degraded: true }).kind).toBe('degraded');
  });

  it('detects agent-backed and report-backed sources', () => {
    expect(resolveSourceTrustBadge({ agentName: 'fundamental_agent' }).label).toBe('agent-backed');
    expect(resolveSourceTrustBadge({ sourceType: 'report_replay' }).label).toBe('report-backed');
  });
});

describe('SourceTrustBadge', () => {
  it('renders a compact badge label', () => {
    const html = renderToStaticMarkup(<SourceTrustBadge sourceType="snapshot" />);

    expect(html).toContain('snapshot');
  });
});

import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { EvidenceLedgerPanel } from './EvidenceLedgerPanel';
import type { EvidenceLedger } from '../../types/index';

const renderText = (node: React.ReactElement) =>
  renderToStaticMarkup(node).replace(/\s+/g, ' ');

describe('EvidenceLedgerPanel', () => {
  it('renders source title, source domain, as_of, confidence, and layer badge', () => {
    const ledger: EvidenceLedger = {
      ledger_id: 'ledger:aapl:test',
      query: 'AAPL margin outlook',
      subject: 'AAPL',
      claims: [
        {
          claim_id: 'claim:aapl:margin',
          claim: 'Apple margin improved year over year.',
          stance: 'bull',
          evidence_ids: ['agent_source:sec:aapl'],
          confidence: 0.81,
          agent_name: 'fundamental_agent',
          task_ids: ['task-1'],
          limitations: ['latest quarter only'],
        },
      ],
      sources: [
        {
          source_id: 'agent_source:sec:aapl',
          title: 'Apple quarterly report',
          url: 'https://www.sec.gov/Archives/edgar/data/aapl.htm',
          source: 'SEC EDGAR',
          published_date: '2026-05-01',
          as_of: '2026-05-02T09:30:00',
          reliability: 0.92,
          freshness_hours: 12,
          layer: 'kb',
          collection: 'kb:stock:AAPL',
        },
      ],
      uncertainties: [],
      contradictions: [],
      coverage_targets: ['margin'],
      created_at: '2026-05-02T10:00:00',
    };

    const text = renderText(<EvidenceLedgerPanel ledger={ledger} />);

    expect(text).toContain('Apple quarterly report');
    expect(text).toContain('sec.gov');
    expect(text).toContain('2026-05-02T09:30:00');
    expect(text).toContain('92%');
    expect(text).toContain('kb');
    expect(text).toContain('agent-backed');
  });

  it('shows a compact empty state for a missing ledger instead of raw JSON', () => {
    const html = renderToStaticMarkup(<EvidenceLedgerPanel ledger={null} />);
    const text = html.replace(/\s+/g, ' ');

    expect(text).toContain('暂无证据账本');
    expect(html).not.toContain('{');
    expect(html).not.toContain('"claims"');
  });
});

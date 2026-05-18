import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { EvidenceLedgerPanel } from './EvidenceLedgerPanel';
import { HoldingsWatchPanel } from './HoldingsWatchPanel';
import type { EvidenceLedger, HoldingsInsight } from '../../types/index';

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
          evidence_ids: ['source:sec:aapl'],
          confidence: 0.81,
          agent_name: 'fundamental_agent',
          task_ids: ['task-1'],
          limitations: ['latest quarter only'],
        },
      ],
      sources: [
        {
          source_id: 'source:sec:aapl',
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
  });

  it('shows a compact empty state for a missing ledger instead of raw JSON', () => {
    const html = renderToStaticMarkup(<EvidenceLedgerPanel ledger={null} />);
    const text = html.replace(/\s+/g, ' ');

    expect(text).toContain('暂无证据账本');
    expect(html).not.toContain('{');
    expect(html).not.toContain('"claims"');
  });
});

describe('HoldingsWatchPanel', () => {
  it('renders 13F delay note and Form 4 transaction rows', () => {
    const holdings: HoldingsInsight = {
      source: 'sec_holdings',
      ticker: 'AAPL',
      holder_name: 'Berkshire Hathaway',
      quarter: '2025Q1',
      regulatory_notes: {
        form_13f_due: 'SEC Form 13F is due within 45 days after each calendar quarter end.',
        form_4_due: 'In most cases, Form 4 is filed within two business days following the transaction date.',
      },
      holdings: [
        {
          issuer_name: 'Apple Inc.',
          ticker: 'AAPL',
          cusip: '037833100',
          value_usd_thousands: 150000,
          shares: 1000,
          share_type: 'SH',
        },
      ],
      transactions: [
        {
          owner_name: 'Jane Officer',
          security_title: 'Common Stock',
          security_type: 'non_derivative',
          transaction_date: '2025-05-01',
          transaction_code: 'P',
          acquired_disposed: 'A',
          shares: 100,
          price_per_share: 185.5,
          direct_or_indirect_ownership: 'D',
          interpretation_note: 'Raw SEC Form 4 code P; do not infer intent from code alone.',
        },
      ],
    };

    const text = renderText(<HoldingsWatchPanel holdings={holdings} />);

    expect(text).toContain('13F');
    expect(text).toContain('45 days');
    expect(text).toContain('Form 4');
    expect(text).toContain('Jane Officer');
    expect(text).toContain('P');
    expect(text).toContain('100');
    expect(text).toContain('$185.50');
  });
});

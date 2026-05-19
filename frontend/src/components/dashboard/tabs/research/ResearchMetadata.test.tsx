import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchMetadata } from './ResearchMetadata';
import type { LatestReportData } from '../../../../hooks/useLatestReport';

const renderText = (node: React.ReactElement) => renderToStaticMarkup(node).replace(/\s+/g, ' ');

describe('ResearchMetadata', () => {
  it('surfaces agent quality contract and RAG layer breakdown', () => {
    const reportData: LatestReportData = {
      report: {
        evidence_quality: {
          overall_score: 0.77,
          agent_quality: {
            status: 'warn',
            metrics: {
              claim_source_ratio: 0.5,
              supported_claim_count: 2,
              claim_count: 4,
            },
            reason_codes: ['unsupported_claim'],
          },
        },
        report_hints: {
          grounding: {
            grounding_rate: 0.7,
            layer_hit_breakdown: [
              { layer: 'memory', count: 1 },
              { layer: 'ws', count: 3 },
              { layer: 'kb', count: 2 },
            ],
          },
        },
      },
      citations: [],
    } as unknown as LatestReportData;

    const text = renderText(<ResearchMetadata reportData={reportData} />);

    expect(text).toContain('Agent 质量');
    expect(text).toContain('warn');
    expect(text).toContain('2/4 claims');
    expect(text).toContain('memory 1');
    expect(text).toContain('ws 3');
    expect(text).toContain('kb 2');
  });
});

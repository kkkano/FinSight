import { describe, expect, it } from 'vitest';

import { buildRagObservabilitySummary } from './ragInspectorStatus';

describe('buildRagObservabilitySummary', () => {
  it('prefers nested observability 24h counters over preview list length', () => {
    const result = buildRagObservabilitySummary(
      {
        observability: {
          enabled: true,
          recent_run_count_24h: 7,
          recent_fallback_count_24h: 3,
          recent_empty_hits_rate_24h: 0.25,
          last_run_at: '2026-03-07T00:00:00Z',
          recent_runs: [{ id: 'run-1', retrieval_hit_count: 0 }, { id: 'run-2', retrieval_hit_count: 2 }],
          fallback_summary: [{ id: 'fb-1' }],
        },
      },
      { status: 'ok' }
    );

    expect(result.summary.enabled).toBe(true);
    expect(result.summary.backend).toBe('ok');
    expect(result.summary.recent_run_count_24h).toBe(7);
    expect(result.summary.recent_fallback_count_24h).toBe(3);
    expect(result.summary.recent_empty_hits_rate_24h).toBe(0.25);
    expect(result.summary.last_run_at).toBe('2026-03-07T00:00:00Z');
    expect(result.recentRuns).toHaveLength(2);
  });

  it('falls back to preview lists when backend counters are absent', () => {
    const result = buildRagObservabilitySummary(
      {
        observability: {
          recent_runs: [{ id: 'run-1', started_at: '2026-03-07T01:00:00Z', retrieval_hit_count: 0 }],
          fallback_summary: [{ id: 'fb-1', created_at: '2026-03-07T01:05:00Z' }],
        },
      },
      { enabled: true, status: 'postgres' }
    );

    expect(result.summary.enabled).toBe(true);
    expect(result.summary.backend).toBe('postgres');
    expect(result.summary.recent_run_count_24h).toBe(1);
    expect(result.summary.recent_fallback_count_24h).toBe(1);
    expect(result.summary.recent_empty_hits_rate_24h).toBe(1);
    expect(result.summary.last_run_at).toBe('2026-03-07T01:00:00Z');
    expect(result.summary.last_fallback_at).toBe('2026-03-07T01:05:00Z');
  });
});

import { describe, expect, it } from 'vitest';
import { usesModelSelection } from './modelRequestScope';

describe('model selection request scope', () => {
  it.each([
    '/api/execute', '/api/execute/resume', '/api/execute/?ticker=AAPL',
  ])('includes the generation path %s', (path) => {
    expect(usesModelSelection(path)).toBe(true);
  });

  it.each([
    '/health', '/api/models', '/api/models/test', '/api/models/capabilities', '/api/config',
    '/api/conversations', '/api/conversations/fixture-session', '/api/user/watchlist/add',
    '/api/stock/price/AAPL', '/api/chart/data', '/api/rebalance/suggestions',
    '/api/rebalance/suggestions/123', '/api/portfolio/summary', '/api/predictions/track-record',
    '/api/benchmarks/us20-v1/track-record',
    '/api/execute-metadata', '/api/dashboard/insights-cache', '/api/config?next=/chat/supervisor',
    '/api/predictions/generate', '/api/execute/runs/fixture/stream', '/api/execute/runs/fixture/cancel',
  ])('excludes the data or management path %s', (path) => {
    expect(usesModelSelection(path)).toBe(false);
  });
});

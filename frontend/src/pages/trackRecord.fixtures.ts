// Test-only fixtures. These values are not historical predictions or real results.
import type { PredictionGroup, PredictionRecord, PredictionTrackRecord } from '../types/predictions';

const tickers = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AVGO', 'AMD', 'JPM', 'BAC', 'V', 'UNH', 'JNJ', 'LLY', 'XOM', 'CVX', 'CAT', 'WMT', 'COST'];
const source = 'yahoo/yfinance-0.2.66';

export function makeTrackRecordFixture(): PredictionTrackRecord {
  const records: PredictionRecord[] = tickers.flatMap((ticker, tickerIndex) =>
    (['direction', 'drawdown'] as const).map((type, taskIndex) => {
      const index = tickerIndex * 2 + taskIndex;
      const status = index < 10 ? 'settled' : index < 34 ? 'pending' : index < 36 ? 'awaiting_data' : index < 38 ? 'failed' : index === 38 ? 'missed' : 'abstained';
      const accepted = index < 36;
      const confirmed = !(tickerIndex === 4 && type === 'direction');
      const direction = tickerIndex === 0 ? 'flat' : tickerIndex === 2 ? 'up' : 'down';
      const actualDirection = tickerIndex === 3 ? 'flat' : 'up';
      const actualEvent = tickerIndex === 4;
      const eventOccurs = tickerIndex === 0;
      const returnPct = tickerIndex === 3 ? 0.004 : 0.03;
      return {
        id: `fixture-${index}`, ticker, agent: type === 'direction' ? 'technical' : 'risk',
        prediction_type: type, batch_date: '2026-09-21', status,
        direction: accepted && type === 'direction' ? direction : null,
        event_occurs: accepted && type === 'drawdown' ? eventOccurs : null,
        reason: '测试 fixture：非真实战绩；仅用于界面验收。',
        evidence_refs: accepted ? ['fixture:snapshot:return_5d', 'fixture:snapshot:realized_volatility'] : [],
        issued_at: accepted ? '2026-09-21T13:00:00Z' : null,
        window_start: '2026-09-21', window_end: '2026-09-25',
        actual_model: confirmed ? 'fixture-model-a' : 'unknown', model_confirmed: confirmed,
        prompt_version: type === 'direction' ? 'fixture-technical-v1' : 'fixture-risk-v1',
        outcome: status === 'settled' ? {
          p0: 100, p5: 100 * (1 + returnPct), return_pct: returnPct,
          max_drawdown: actualEvent ? 0.07 : 0.02,
          actual_direction: actualDirection, actual_event: actualEvent,
          hit: type === 'direction' ? direction === actualDirection : eventOccurs === actualEvent,
          baseline_hit: type === 'direction' ? actualDirection === 'up' : !actualEvent,
          source, settled_at: '2026-09-25T21:00:00Z',
        } : null,
        error_code: status === 'failed' ? 'fixture_timeout' : status === 'awaiting_data' ? 'fixture_missing_data' : null,
      };
    }));
  const baseGroup: PredictionGroup = {
    agent: 'technical', prediction_type: 'direction', actual_model: 'fixture-model-a', model_confirmed: true,
    prompt_version: 'fixture-technical-v1', strategy_version: 'fixture-strategy-v1', scorer_version: 'fixture-scorer-v1',
    n: 4, hits: 1, hit_rate: 0.25, baseline_hits: 3, baseline_hit_rate: 0.75, delta: -0.5,
    tp: 0, fp: 0, tn: 0, fn: 0,
  };
  return {
    enabled: true,
    universe: { version: 'fixture-us20-v1（测试数据，非真实战绩）', tickers: [...tickers] },
    coverage: {
      batch_date: '2026-09-21', expected: 40, accepted: 36, attempts: 45,
      counts: { settled: 10, pending: 24, awaiting_data: 2, failed: 2, missed: 1, abstained: 1 },
      last_update: '2026-09-25T21:00:00Z',
    },
    summary: {
      opportunities: 40, predictions: 36, settled: 10, pending: 24, failed: 2,
      missed: 1, abstained: 1, awaiting_data: 2, batch_count: 1, stock_count: 20,
    },
    groups: [
      baseGroup,
      { ...baseGroup, actual_model: 'unknown', model_confirmed: false, n: 1, hits: 0, hit_rate: 0, baseline_hits: 1, baseline_hit_rate: 1, delta: -1 },
      {
        ...baseGroup, agent: 'risk', prediction_type: 'drawdown', prompt_version: 'fixture-risk-v1',
        n: 5, hits: 3, hit_rate: 0.6, baseline_hits: 4, baseline_hit_rate: 0.8, delta: -0.2,
        tp: 0, fp: 1, tn: 3, fn: 1,
      },
    ],
    records,
    metadata: { source, horizon_sessions: 5, direction_threshold: 0.005, drawdown_threshold: 0.05 },
  };
}

export function makeEmptyTrackRecordFixture(): PredictionTrackRecord {
  const data = makeTrackRecordFixture();
  return {
    ...data, enabled: false, groups: [], records: [],
    coverage: { batch_date: null, expected: 40, accepted: 0, attempts: 0, counts: {}, last_update: null },
    summary: { opportunities: 0, predictions: 0, settled: 0, pending: 0, failed: 0, missed: 0, abstained: 0, awaiting_data: 0, batch_count: 0, stock_count: 0 },
  };
}

export function makePendingTrackRecordFixture(): PredictionTrackRecord {
  const data = makeTrackRecordFixture();
  return {
    ...data, groups: [],
    coverage: { ...data.coverage, accepted: 40, attempts: 40, counts: { pending: 40 } },
    summary: { ...data.summary, predictions: 40, settled: 0, pending: 40, failed: 0, missed: 0, abstained: 0, awaiting_data: 0 },
    records: data.records.map((record) => ({
      ...record, status: 'pending', outcome: null, error_code: null,
      direction: record.prediction_type === 'direction' ? 'up' : null,
      event_occurs: record.prediction_type === 'drawdown' ? false : null,
      issued_at: '2026-09-21T13:00:00Z',
    })),
  };
}

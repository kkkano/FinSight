import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { PredictionHistoryItem } from '../../api/domains/predictions';
import { useStore } from '../../store/useStore';
import { PersonalPredictionDetail, RightPanelTrackRecordTab } from './RightPanelTrackRecordTab';
import { PERSONAL_PAGE_SIZE, loadPersonalPredictionPage } from './personalTrackRecord';

const render = (node: ReactNode) => renderToStaticMarkup(
  <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>,
);

const item: PredictionHistoryItem = {
  prediction: {
    prediction_id: '11111111-1111-4111-8111-111111111111', run_id: '22222222-2222-4222-8222-222222222222',
    symbol: 'AAPL', agent: 'prediction_analyst', direction: 'short', confidence: 0.58,
    thesis: '强趋势中的条件性回落假设。', anchor: { timeframe: '1d', time: '2026-10-02', price: 333.26 },
    entry: 333, stop: 338.2, target1: 325.2, target2: 318.6, scenarios: [],
    source_type: 'ai', prompt_version: 'fixture-v1', status: 'hit_target',
    created_at: '2026-10-02T12:00:00Z', updated_at: '2026-10-02T18:00:00Z',
  },
  outcome: { prediction_id: '11111111-1111-4111-8111-111111111111', status: 'hit_target', pct_since_anchor: -2.001,
    evaluated_through: '2026-10-02T18:00:00Z', algorithm_version: 'fixture-v1', resolution_reason: '目标价已触及' },
};

afterEach(() => useStore.getState().setAuthIdentity(null));

describe('personal prediction track record', () => {
  it('requests filters and server pagination, using one extra record only to discover the next page', async () => {
    const reader = vi.fn(async () => ({ items: Array.from({ length: PERSONAL_PAGE_SIZE + 1 }, () => item), limit: PERSONAL_PAGE_SIZE + 1, offset: 40 }));
    const controller = new AbortController();
    const page = await loadPersonalPredictionPage({ symbol: 'AAPL', direction: 'short', offset: 40 }, controller.signal, reader);
    expect(reader).toHaveBeenCalledWith({ symbol: 'AAPL', direction: 'short', offset: 40, limit: 21 }, controller.signal);
    expect(page.items).toHaveLength(20);
    expect(page.hasMore).toBe(true);
  });

  it('stops paging for a final or empty response and preserves failures', async () => {
    const reader = vi.fn(async () => ({ items: [item], limit: 21, offset: 0 }));
    expect((await loadPersonalPredictionPage({ offset: 0 }, undefined, reader)).hasMore).toBe(false);
    const failedReader = vi.fn(async () => { throw new Error('fixture failure'); });
    await expect(loadPersonalPredictionPage({ offset: 0 }, undefined, failedReader)).rejects.toThrow('fixture failure');
  });

  it('explains an ended bearish hypothesis and formats percentage points without multiplying twice', () => {
    const markup = render(<PersonalPredictionDetail item={item} />);
    expect(markup).toContain('原判断：回落假设');
    expect(markup).toContain('历史判断');
    expect(markup).toContain('不代表当前观点');
    expect(markup).toContain('未定义固定持有天数');
    expect(markup).toContain('-2.0%');
    expect(markup).not.toContain('-200.1%');
    expect(markup).toContain('目标价已触及');
  });

  it('does not invent an outcome for an open hypothesis', () => {
    const markup = render(<PersonalPredictionDetail item={{ prediction: { ...item.prediction, status: 'open' }, outcome: null }} />);
    expect(markup).toContain('AI 回落假设');
    expect(markup).toContain('尚未产生最终结果');
    expect(markup).not.toContain('不代表当前观点');
  });

  it('gates personal records for anonymous users and returns to the actual workspace after login', () => {
    useStore.getState().setAuthIdentity(null);
    const markup = render(<MemoryRouter initialEntries={['/dashboard/AAPL?analysis=prediction']}><RightPanelTrackRecordTab initialView="personal" symbol="AAPL" /></MemoryRouter>);
    expect(markup).toContain('personal-track-record-login');
    expect(markup).toContain('/welcome?from=%2Fdashboard%2FAAPL%3Fanalysis%3Dprediction');
    expect(markup).not.toContain('personal-record-row');
    expect(markup).not.toContain('us20-track-record');
  });
});

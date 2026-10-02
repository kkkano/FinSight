import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from './client';
import { useModelSelectionStore } from '../store/modelSelection';
import { makeEmptyTrackRecordFixture } from '../pages/trackRecord.fixtures';

afterEach(() => {
  useModelSelectionStore.getState().clearSelection();
  vi.unstubAllGlobals();
});

describe('public prediction ledger client', () => {
  it('reads anonymously without forwarding the current model key', async () => {
    useModelSelectionStore.getState().applySelection({
      source: 'custom', base_url: 'https://api.example.com/v1', api_key: 'fixture-never-send', model: 'fixture-model',
      context_acknowledged: true,
    }, { provider: 'custom', label: 'Custom', icon_url: null, docs_url: null, effort_options: [], default_effort: null });
    const fixture = makeEmptyTrackRecordFixture();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    expect(await apiClient.getPredictionTrackRecord(50, 200, controller.signal)).toEqual(fixture);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/benchmarks/us20-v1/track-record?limit=50&offset=200'), {
      headers: { Accept: 'application/json' }, credentials: 'omit', signal: controller.signal,
    });
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain('fixture-never-send');
  });

  it('does not turn a failed ledger read into a zero-score dataset', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Internal details', { status: 503 })));
    await expect(apiClient.getPredictionTrackRecord()).rejects.toThrow('战绩数据暂时不可用，请稍后重试。');
  });
});

import { buildApiUrl } from '../../config/runtime';
import type { PredictionTrackRecord } from '../../types/predictions';

export interface TrackRecordFilters {
  ticker?: string;
  status?: string;
  prediction_type?: 'direction' | 'drawdown';
}

export const trackRecordApi = {
  async getPredictionTrackRecord(limit = 50, offset = 0, signal?: AbortSignal, filters: TrackRecordFilters = {}): Promise<PredictionTrackRecord> {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (filters.ticker) params.set('ticker', filters.ticker);
    if (filters.status) params.set('status', filters.status);
    if (filters.prediction_type) params.set('prediction_type', filters.prediction_type);
    const response = await fetch(`${buildApiUrl('/api/benchmarks/us20-v1/track-record')}?${params}`, {
      headers: { Accept: 'application/json' }, credentials: 'omit', signal,
    });
    if (!response.ok) throw new Error('战绩数据暂时不可用，请稍后重试。');
    return response.json();
  },
};

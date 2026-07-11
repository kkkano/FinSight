import { apiClient } from '../api/client';
import {
  MAX_AUTO_CHART_TICKERS,
  extractTickers,
  mergeTickerCandidates,
} from './ticker';

const CHART_KEYWORDS = ['trend', 'chart', 'kline', 'k-line', '走势', '趋势', '图表', 'k线'];
const INLINE_RENDERABLE_TYPES = new Set(['line', 'candlestick', 'area']);
const INLINE_RENDERABLE_DATA_KINDS = new Set(['kline', 'technical']);
const SMARTCHART_DATA_TYPES = new Set(['pie', 'bar']);
const SMARTCHART_DATA_KINDS = new Set(['composition', 'comparison']);
const CHART_MARKER_PATTERN = /\[CHART:([A-Z0-9.^=-]+):([a-z]+)\]/g;

export interface ChartIntentResult {
  tickers: string[];
  chartType: string | null;
  smartChart?: { chartType: string; dataKind: string; title: string } | null;
}

/** InlineChart 只有 K 线数据源，非 K 线类型必须走 SmartChart 或诚实跳过。 */
export function isInlineChartRenderable(chartType: string | null, dataKind: string | null): boolean {
  if (!chartType || !INLINE_RENDERABLE_TYPES.has(chartType)) return false;
  return !dataKind || INLINE_RENDERABLE_DATA_KINDS.has(dataKind);
}

export function shouldUseSmartChartData(chartType: string | null, dataKind: string | null): boolean {
  if (!chartType || !dataKind) return false;
  return SMARTCHART_DATA_TYPES.has(chartType) && SMARTCHART_DATA_KINDS.has(dataKind);
}

/** 统一 API 检测与本地关键词回退，供发送和重试路径复用。 */
export async function shouldGenerateChart(
  query: string,
  currentTicker?: string | null,
): Promise<ChartIntentResult> {
  try {
    const response = await apiClient.detectChartType(query, currentTicker || undefined);
    const apiCandidates = Array.isArray(response?.ticker_candidates)
      ? response.ticker_candidates.map((value: unknown) => String(value))
      : [];
    const resolvedTicker = typeof response?.resolved_ticker === 'string' && response.resolved_ticker.trim()
      ? [response.resolved_ticker]
      : [];
    const merged = mergeTickerCandidates(
      apiCandidates,
      resolvedTicker,
      extractTickers(query),
      currentTicker ? [currentTicker] : [],
    );

    if (response.success && response.should_generate) {
      const chartType = response.chart_type || 'line';
      const dataKind = typeof response.data_kind === 'string' ? response.data_kind : null;
      if (isInlineChartRenderable(chartType, dataKind)) return { tickers: merged, chartType };
      if (shouldUseSmartChartData(chartType, dataKind)) {
        return {
          tickers: merged,
          chartType: null,
          smartChart: {
            chartType,
            dataKind: dataKind as string,
            title: typeof response.title === 'string' ? response.title.trim() : '',
          },
        };
      }
      return { tickers: merged, chartType: null, smartChart: null };
    }
  } catch (error) {
    console.error('Chart detection failed:', error);
  }

  const lowerQuery = query.toLowerCase();
  if (!CHART_KEYWORDS.some((keyword) => lowerQuery.includes(keyword))) {
    return { tickers: [], chartType: null, smartChart: null };
  }

  return {
    tickers: mergeTickerCandidates(extractTickers(query), currentTicker ? [currentTicker] : []),
    chartType: 'line',
    smartChart: null,
  };
}

/** 追加缺失的 `[CHART:ticker:type]` 标记；多 ticker 时统一使用折线并最多注入三个。 */
export function injectChartMarkers(
  content: string,
  tickers: string[],
  chartType: string | null,
): string {
  const targets = mergeTickerCandidates(tickers).slice(0, MAX_AUTO_CHART_TICKERS);
  const forceMulti = targets.length > 1;
  if (targets.length === 0 || (!chartType && !forceMulti)) return content;

  const existing = new Set(Array.from(content.matchAll(CHART_MARKER_PATTERN)).map((match) => match[1]));
  const markerType = forceMulti ? 'line' : (chartType || 'line');
  return targets
    .filter((ticker) => !existing.has(ticker))
    .reduce((result, ticker) => `${result}\n\n[CHART:${ticker}:${markerType}]`, content);
}

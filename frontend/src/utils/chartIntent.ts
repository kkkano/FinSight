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
const CHART_MARKER_PATTERN = /\[CHART:([A-Z0-9.^=-]+):([a-z]+)(?::(close|return))?(?::([a-z0-9]+))?\]/g;
const RETURN_KEYWORDS = ['收益率', '回报率', '累计收益', '累计回报', '涨跌幅', 'return', 'performance'];

export interface ChartMarker {
  ticker: string;
  chartType: string;
  valueMode: 'close' | 'return';
  period: string;
}

export interface ChartIntentResult {
  tickers: string[];
  chartType: string | null;
  valueMode?: 'close' | 'return';
  period?: string;
  smartChart?: { chartType: string; dataKind: string; title: string } | null;
}

export function inferChartPeriod(query: string): string {
  const normalized = query.toLowerCase().replace(/\s+/g, '');
  if (/(?:最近|近|过去)?(?:一天|1天|今日|当天)/.test(normalized)) return '1d';
  if (/(?:最近|近|过去)?(?:一周|1周|7天)/.test(normalized)) return '5d';
  if (/(?:最近|近|过去)?(?:一个月|1个月|1月)/.test(normalized)) return '1mo';
  if (/(?:最近|近|过去)?(?:三个月|3个月|3月)/.test(normalized)) return '3mo';
  if (/(?:最近|近|过去)?(?:半年|六个月|6个月|6月)/.test(normalized)) return '6mo';
  if (/(?:最近|近|过去)?(?:两年|2年)/.test(normalized)) return '2y';
  if (/(?:最近|近|过去)?(?:五年|5年)/.test(normalized)) return '5y';
  if (/(?:最近|近|过去)?(?:一年|1年)/.test(normalized)) return '1y';
  return '1y';
}

export function inferChartValueMode(query: string, chartType: string | null): 'close' | 'return' {
  const normalized = query.toLowerCase();
  if (chartType === 'area' || RETURN_KEYWORDS.some((keyword) => normalized.includes(keyword))) return 'return';
  return 'close';
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
      if (isInlineChartRenderable(chartType, dataKind)) {
        return {
          tickers: merged,
          chartType,
          valueMode: merged.length > 1 ? 'return' : inferChartValueMode(query, chartType),
          period: inferChartPeriod(query),
        };
      }
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
    valueMode: inferChartValueMode(query, 'line'),
    period: inferChartPeriod(query),
    smartChart: null,
  };
}

export function parseChartMarkers(content: string): ChartMarker[] {
  return Array.from(content.matchAll(CHART_MARKER_PATTERN)).map((match) => ({
    ticker: match[1],
    chartType: match[2],
    valueMode: match[3] === 'close' ? 'close' : 'return',
    period: match[4] || '1y',
  }));
}

/** 追加缺失的图表标记；新标记携带数值语义和时间范围，旧标记继续按 return/1y 兼容。 */
export function injectChartMarkers(
  content: string,
  tickers: string[],
  chartType: string | null,
  options: { valueMode?: 'close' | 'return'; period?: string } = {},
): string {
  const targets = mergeTickerCandidates(tickers).slice(0, MAX_AUTO_CHART_TICKERS);
  const forceMulti = targets.length > 1;
  if (targets.length === 0 || (!chartType && !forceMulti)) return content;

  const existing = new Set(Array.from(content.matchAll(CHART_MARKER_PATTERN)).map((match) => match[1]));
  const markerType = forceMulti ? 'line' : (chartType || 'line');
  const valueMode = forceMulti ? 'return' : (options.valueMode || 'return');
  const period = options.period || '1y';
  return targets
    .filter((ticker) => !existing.has(ticker))
    .reduce((result, ticker) => `${result}\n\n[CHART:${ticker}:${markerType}:${valueMode}:${period}]`, content);
}

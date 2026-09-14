import { useEffect, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { ChartNoAxesCombined, Loader2 } from 'lucide-react';

import { apiClient } from '../api/client';
import { useChartTheme } from '../hooks/useChartTheme';
import type { ChartType, KlineData } from '../types';
import {
  buildCandlestickOption,
  buildKlineSmartChartData,
  buildLineOption,
} from './SmartChart';
import { SourceBadge } from './ui/SourceBadge';
import { EmptyState } from './ui/EmptyState';

interface InlineChartProps {
  ticker: string;
  period?: string;
  chartType?: ChartType;
  /** 价格语义图使用 close；旧的收益率快捷图保持 return。 */
  valueMode?: 'close' | 'return';
}

const chartLabels: Partial<Record<ChartType, string>> = {
  candlestick: 'K-Line',
  line: 'Return trend',
  area: 'Cumulative returns',
  pie: 'Distribution',
  bar: 'Monthly compare',
  scatter: 'Correlation',
  heatmap: 'Heat map',
  tree: 'Hierarchy',
};

export const InlineChart: React.FC<InlineChartProps> = ({
  ticker,
  period = '1y',
  chartType = 'line',
  valueMode = 'return',
}) => {
  const chartTheme = useChartTheme();
  const [data, setData] = useState<KlineData[]>([]);
  const [dataSource, setDataSource] = useState<string | null>(null);
  const [dataAsOf, setDataAsOf] = useState<string | null>(null);
  const [dataQuality, setDataQuality] = useState<'trusted' | 'degraded' | null>(null);
  const [dataDegraded, setDataDegraded] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  useEffect(() => {
    let active = true;
    const loadData = async () => {
      setLoading(true);
      setLoadError(false);
      try {
        const interval = period === '1y' || period === '2y' ? '1d' : period === '5y' ? '1wk' : '1d';
        const res = await apiClient.fetchKline(ticker, period, interval);
        const responseData = res as any;
        const kline = responseData?.data?.kline_data ?? responseData?.kline_data ?? [];
        const source = responseData?.data?.provider ?? responseData?.data?.source
          ?? responseData?.provider ?? responseData?.source ?? null;
        const asOf = responseData?.data?.as_of ?? responseData?.as_of ?? null;
        const quality = responseData?.data?.quality ?? responseData?.quality ?? null;
        const degraded = responseData?.data?.degraded ?? responseData?.degraded ?? false;
        const responseErrorCode = responseData?.data?.error_code ?? responseData?.error_code ?? null;

        if (!active) return;
        setData(kline);
        setDataSource(typeof source === 'string' ? source : null);
        setDataAsOf(typeof asOf === 'string' ? asOf : null);
        setDataQuality(quality === 'trusted' || quality === 'degraded' ? quality : null);
        setDataDegraded(Boolean(degraded));
        setErrorCode(typeof responseErrorCode === 'string' ? responseErrorCode : null);
      } catch (err) {
        console.error('Inline chart load failed:', err);
        if (active) setLoadError(true);
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    loadData();
    return () => {
      active = false;
    };
  }, [ticker, period, retryKey]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-4 text-fin-muted">
        <Loader2 className="animate-spin mr-2" size={16} />
        Loading chart data...
      </div>
    );
  }

  if (data.length === 0) {
    const noDataMessage = errorCode === 'market_data_unavailable'
      ? '真实行情源暂时不可用，未生成任何占位数据。'
      : '行情源没有返回有效 K 线。';
    return (
      <div className="my-4 rounded-lg border border-fin-border bg-fin-panel px-4">
        <EmptyState
          icon={ChartNoAxesCombined}
          message={loadError ? '行情请求失败，请稍后重试。' : noDataMessage}
          action={{ label: '重试', onClick: () => setRetryKey((value) => value + 1) }}
        />
      </div>
    );
  }

  const isDegraded = dataDegraded || dataQuality !== 'trusted';

  const effectiveValueMode = chartType === 'candlestick' ? 'close' : valueMode;
  const smartData = buildKlineSmartChartData(data, effectiveValueMode);
  if (effectiveValueMode === 'close') {
    smartData.unit = inferTickerPriceUnit(ticker);
  }
  const chartLabel = chartType === 'line' && effectiveValueMode === 'close'
    ? 'Price trend'
    : chartLabels[chartType] || 'Chart';
  const title = `${ticker} ${chartLabel} (${period})`;
  const option = chartType === 'candlestick'
    ? buildCandlestickOption(smartData, title, chartTheme)
    : buildLineOption(smartData, title, chartTheme, chartType === 'area');

  return (
    <div className="my-4 p-4 bg-fin-panel rounded-lg border border-fin-border">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-xs text-fin-muted">
          {ticker} {chartLabel} ({period})
        </div>
        <SourceBadge
          source={dataSource ?? undefined}
          asOf={dataAsOf}
          degraded={isDegraded}
        />
      </div>
      {isDegraded && (
        <div className="mb-2 px-3 py-2 rounded-md border border-amber-500/50 bg-amber-500/10 text-amber-600 text-xs font-medium">
          降级行情仅供查看，不会用于 AI Prediction 或 Outcome。
        </div>
      )}
      <ReactECharts
        option={option}
        style={{ height: '300px', width: '100%' }}
        opts={{ renderer: data.length > 200 ? 'canvas' : 'svg' }}
      />
    </div>
  );
};

function inferTickerPriceUnit(ticker: string): string {
  const normalized = ticker.trim().toUpperCase();
  if (normalized.endsWith('.HK')) return 'HK$';
  if (/\.(?:SS|SZ|BJ)$/.test(normalized)) return '¥';
  if (normalized.endsWith('.L')) return '£';
  if (/\.(?:PA|DE|AS|MI)$/.test(normalized)) return '€';
  if (normalized.endsWith('.T')) return '¥';
  return '$';
}

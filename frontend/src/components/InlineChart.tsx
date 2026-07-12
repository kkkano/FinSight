import { useEffect, useRef, useState } from 'react';
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
  onDataReady?: (data: KlineData[], summary: string) => void;
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

const generateDataSummary = (ticker: string, data: KlineData[]): string => {
  if (!data.length) return '';

  const first = data[0];
  const last = data[data.length - 1];
  const prices = data.map((d) => d.close);
  const high = Math.max(...prices);
  const low = Math.min(...prices);
  const change = last.close - first.close;
  const changePercent = (change / first.close) * 100;

  return `
[${ticker} Historical Snapshot]
Range: ${first.time} -> ${last.time}
Start: $${first.close.toFixed(2)}
Last: $${last.close.toFixed(2)}
High: $${high.toFixed(2)}
Low: $${low.toFixed(2)}
Return: ${change >= 0 ? '+' : ''}$${change.toFixed(2)} (${changePercent >= 0 ? '+' : ''}${changePercent.toFixed(2)}%)
Points: ${data.length}
`;
};

export const InlineChart: React.FC<InlineChartProps> = ({
  ticker,
  period = '1y',
  chartType = 'line',
  onDataReady,
}) => {
  const chartTheme = useChartTheme();
  const [data, setData] = useState<KlineData[]>([]);
  // 数据来源标记：price_fallback* 表示后端全源失败后生成的合成占位 K 线（非真实行情）
  const [dataSource, setDataSource] = useState<string | null>(null);
  const [dataAsOf, setDataAsOf] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const onDataReadyRef = useRef(onDataReady);
  const lastSummaryRef = useRef<string>('');

  useEffect(() => {
    onDataReadyRef.current = onDataReady;
  }, [onDataReady]);

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
        // 读取后端 source 标记（price_fallback / price_fallback_hourly = 合成占位行情）
        const source = responseData?.data?.source ?? responseData?.source ?? null;
        const asOf = responseData?.data?.as_of ?? responseData?.as_of ?? null;

        if (!active) return;
        setData(kline);
        setDataSource(typeof source === 'string' ? source : null);
        setDataAsOf(typeof asOf === 'string' ? asOf : null);
        if (kline.length) {
          const summary = generateDataSummary(ticker, kline);
          if (summary && summary !== lastSummaryRef.current) {
            lastSummaryRef.current = summary;
            onDataReadyRef.current?.(kline, summary);
          }
        }
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
    return (
      <div className="my-4 rounded-lg border border-fin-border bg-fin-panel px-4">
        <EmptyState
          icon={ChartNoAxesCombined}
          message={loadError ? '行情图暂不可用，请稍后重试。' : '行情图暂不可用：数据源没有返回有效行情。'}
          action={{ label: '重试', onClick: () => setRetryKey((value) => value + 1) }}
        />
      </div>
    );
  }

  // 合成占位数据：后端全源失败后用最新价生成的等值序列，非真实行情，必须显著标注
  const isSynthetic = typeof dataSource === 'string' && dataSource.startsWith('price_fallback');

  const smartData = buildKlineSmartChartData(
    data,
    chartType === 'candlestick' ? 'close' : 'return',
  );
  const title = `${ticker} ${chartLabels[chartType] || 'Chart'} (${period})`;
  const option = chartType === 'candlestick'
    ? buildCandlestickOption(smartData, title, chartTheme)
    : buildLineOption(smartData, title, chartTheme, chartType === 'area');

  return (
    <div className="my-4 p-4 bg-fin-panel rounded-lg border border-fin-border">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-xs text-fin-muted">
          {ticker} {chartLabels[chartType] || 'Chart'} ({period})
        </div>
        <SourceBadge
          source={dataSource ?? undefined}
          asOf={dataAsOf}
          synthetic={isSynthetic}
          degraded={isSynthetic}
        />
      </div>
      {isSynthetic && (
        <div className="mb-2 px-3 py-2 rounded-md border border-amber-500/50 bg-amber-500/10 text-amber-600 text-xs font-medium">
          ⚠ 合成占位 · 非真实行情：实时数据源全部失败，下图为按最新价生成的等值占位序列，仅供形态参考，不可用于交易决策。
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

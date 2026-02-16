import { useEffect, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { Loader2 } from 'lucide-react';

import { apiClient } from '../api/client';
import { useChartTheme } from '../hooks/useChartTheme';
import type { ChartType, KlineData } from '../types';

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

const buildLineOption = (data: KlineData[], chartTheme: ReturnType<typeof useChartTheme>, fillArea = false) => {
  const returns = data.map((item, idx) => {
    const firstClose = data[0].close;
    const value = ((item.close - firstClose) / firstClose) * 100;
    return { time: item.time, value, idx };
  });

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: chartTheme.tooltipBackground,
      borderColor: chartTheme.tooltipBorder,
      textStyle: { color: chartTheme.tooltipText },
      formatter: (params: any) => {
        const point = params[0];
        const sign = point.value >= 0 ? '+' : '';
        return `${point.axisValue}<br/>Return: <span style="color: ${point.value >= 0 ? chartTheme.success : chartTheme.danger}">${sign}${point.value.toFixed(2)}%</span>`;
      },
    },
    grid: { left: '10%', right: '10%', bottom: '15%', top: '10%' },
    xAxis: {
      type: 'category',
      data: returns.map((item) => item.time),
      axisLine: { lineStyle: { color: chartTheme.border } },
      axisLabel: {
        color: chartTheme.muted,
        fontSize: 10,
        rotate: 0,
        hideOverlap: true,
        interval: 'auto',
        formatter: (value: string) => {
          // 优先显示日期部分（MM-DD），而非时间
          if (!value) return '';
          // 如果包含空格（如 "2024-01-15 00:00:00"），取日期部分
          const datePart = value.includes(' ') ? value.split(' ')[0] : value;
          // 如果是 YYYY-MM-DD 格式，返回 MM-DD
          if (datePart.includes('-') && datePart.length >= 10) {
            return datePart.slice(5); // MM-DD
          }
          // 如果是短日期格式，直接返回
          if (datePart.includes('-')) return datePart.slice(5);
          return datePart;
        }
      },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: chartTheme.grid } },
      axisLabel: {
        color: chartTheme.textSecondary,
        fontSize: 10,
        formatter: (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`,
      },
    },
    series: [
      {
        type: 'line',
        data: returns.map((item) => item.value),
        smooth: true,
        lineStyle: { color: chartTheme.primary, width: 2 },
        areaStyle: fillArea
          ? {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: chartTheme.primarySoft },
                { offset: 1, color: chartTheme.primaryFaint },
              ],
            },
          }
          : undefined,
        itemStyle: { color: chartTheme.primary },
      },
    ],
  };
};

const buildCandleOption = (data: KlineData[], chartTheme: ReturnType<typeof useChartTheme>) => ({
  backgroundColor: 'transparent',
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'cross' },
    backgroundColor: chartTheme.tooltipBackground,
    borderColor: chartTheme.tooltipBorder,
    textStyle: { color: chartTheme.tooltipText },
  },
  grid: { left: '10%', right: '10%', bottom: '15%', top: '10%' },
  xAxis: {
    type: 'category',
    data: data.map((item) => item.time),
    axisLine: { lineStyle: { color: chartTheme.border } },
    axisLabel: { color: chartTheme.textSecondary, fontSize: 10, rotate: 45 },
  },
  yAxis: {
    scale: true,
    axisLine: { show: false },
    splitLine: { lineStyle: { color: chartTheme.grid } },
    axisLabel: { color: chartTheme.textSecondary, fontSize: 10 },
  },
  series: [
    {
      type: 'candlestick',
      data: data.map((item) => [item.open, item.close, item.low, item.high]),
      itemStyle: {
        color: chartTheme.success,
        color0: chartTheme.danger,
        borderColor: chartTheme.success,
        borderColor0: chartTheme.danger,
      },
    },
  ],
});

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
  const [loading, setLoading] = useState(true);
  const onDataReadyRef = useRef(onDataReady);
  const lastSummaryRef = useRef<string>('');

  useEffect(() => {
    onDataReadyRef.current = onDataReady;
  }, [onDataReady]);

  useEffect(() => {
    let active = true;
    const loadData = async () => {
      setLoading(true);
      try {
        const interval = period === '1y' || period === '2y' ? '1d' : period === '5y' ? '1wk' : '1d';
        const res = await apiClient.fetchKline(ticker, period, interval);
        const responseData = res as any;
        const kline = responseData?.data?.kline_data ?? responseData?.kline_data ?? [];

        if (!active) return;
        setData(kline);
        if (kline.length) {
          const summary = generateDataSummary(ticker, kline);
          if (summary && summary !== lastSummaryRef.current) {
            lastSummaryRef.current = summary;
            onDataReadyRef.current?.(kline, summary);
          }
        }
      } catch (err) {
        console.error('Inline chart load failed:', err);
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
  }, [ticker, period]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-4 text-fin-muted">
        <Loader2 className="animate-spin mr-2" size={16} />
        Loading chart data...
      </div>
    );
  }

  if (data.length === 0) {
    return null;
  }

  const option = chartType === 'candlestick'
    ? buildCandleOption(data, chartTheme)
    : buildLineOption(data, chartTheme, chartType === 'area');

  return (
    <div className="my-4 p-4 bg-fin-panel rounded-lg border border-fin-border">
      <div className="text-xs text-fin-muted mb-2">
        {ticker} {chartLabels[chartType] || 'Chart'} ({period})
      </div>
      <ReactECharts option={option} style={{ height: '300px', width: '100%' }} />
    </div>
  );
};


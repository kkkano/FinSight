/**
 * Market Chart Card - 专业级 K 线图组件
 *
 * 功能：
 * - 支持多种图表类型切换（K线、折线、面积、山形）
 * - 支持时间范围选择（1D, 1W, 1M, 3M, 6M, 1Y, ALL）
 * - 成交量副图
 * - MA5/MA10 均线
 * - Brush 框选工具
 * - DataZoom 缩放
 *
 * 参考 ECharts candlestick-brush 示例
 */
import { useState, useMemo, useCallback } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { BarChart3, LineChart, TrendingUp, Activity } from 'lucide-react';
import type { ChartPoint } from '../../types/dashboard';

// 图表类型定义
type ChartType = 'candlestick' | 'line' | 'area' | 'mountain';

// 时间范围定义
type TimeRange = '1D' | '1W' | '1M' | '3M' | '6M' | '1Y' | 'ALL';

interface MarketChartCardProps {
  data: ChartPoint[];
  loading?: boolean;
  title?: string;
}

// 图表类型配置
const CHART_TYPES: { value: ChartType; label: string; icon: React.ReactNode }[] = [
  { value: 'candlestick', label: 'K线', icon: <BarChart3 size={14} /> },
  { value: 'line', label: '折线', icon: <LineChart size={14} /> },
  { value: 'area', label: '面积', icon: <TrendingUp size={14} /> },
  { value: 'mountain', label: '山形', icon: <Activity size={14} /> },
];

// 时间范围配置
const TIME_RANGES: { value: TimeRange; label: string }[] = [
  { value: '1D', label: '1天' },
  { value: '1W', label: '1周' },
  { value: '1M', label: '1月' },
  { value: '3M', label: '3月' },
  { value: '6M', label: '6月' },
  { value: '1Y', label: '1年' },
  { value: 'ALL', label: '全部' },
];

// 计算移动平均线
function calculateMA(data: number[], dayCount: number): (number | null)[] {
  const result: (number | null)[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i < dayCount - 1) {
      result.push(null);
      continue;
    }
    let sum = 0;
    for (let j = 0; j < dayCount; j++) {
      sum += data[i - j];
    }
    result.push(+(sum / dayCount).toFixed(2));
  }
  return result;
}

export function MarketChartCard({
  data,
  loading,
  title = '价格走势',
}: MarketChartCardProps) {
  const [chartType, setChartType] = useState<ChartType>('candlestick');
  const [timeRange, setTimeRange] = useState<TimeRange>('1M');

  // 根据时间范围过滤数据
  const filteredData = useMemo(() => {
    if (!data || data.length === 0) return [];

    // 用数据中最新时间作为锚点
    const latestTs = data.reduce((max, d) => {
      const t = d.time;
      return typeof t === 'number' && t > max ? t : max;
    }, 0);
    const anchor = latestTs > 0 ? latestTs : Date.now() / 1000;

    const ranges: Record<TimeRange, number> = {
      '1D': 24 * 60 * 60,
      '1W': 7 * 24 * 60 * 60,
      '1M': 30 * 24 * 60 * 60,
      '3M': 90 * 24 * 60 * 60,
      '6M': 180 * 24 * 60 * 60,
      '1Y': 365 * 24 * 60 * 60,
      'ALL': Infinity,
    };

    if (timeRange === 'ALL') return data;

    const cutoff = anchor - ranges[timeRange];
    const next = data.filter((d) => !d.time || d.time >= cutoff);

    return next.length > 0 ? next : data;
  }, [data, timeRange]);

  // 格式化时间
  const formatTime = useCallback(
    (timestamp?: number) => {
      if (!timestamp) return '';
      const date = new Date(timestamp * 1000);
      if (timeRange === '1D') {
        return `${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
      }
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    },
    [timeRange]
  );

  // 判断是否有 OHLC 数据
  const hasOHLC = useMemo(() => {
    return filteredData.some(
      (d) =>
        d.open !== undefined &&
        d.high !== undefined &&
        d.low !== undefined &&
        d.close !== undefined
    );
  }, [filteredData]);

  // 判断是否有成交量数据
  const hasVolume = useMemo(() => {
    return filteredData.some((d) => d.volume !== undefined && d.volume > 0);
  }, [filteredData]);

  // 生成 ECharts 配置
  const option = useMemo((): EChartsOption | null => {
    if (filteredData.length === 0) return null;

    const xData = filteredData.map((d) => formatTime(d.time) || d.period || '');
    const closeData = filteredData.map((d) => d.close || d.value || 0);
    const volumeData = filteredData.map((d) => d.volume || 0);

    // 计算涨跌颜色
    const isUp = closeData.length >= 2 ? closeData[closeData.length - 1] >= closeData[0] : true;
    const mainColor = isUp ? '#10b981' : '#ef4444';
    const areaGradient = isUp
      ? ['rgba(16, 185, 129, 0.4)', 'rgba(16, 185, 129, 0.05)']
      : ['rgba(239, 68, 68, 0.4)', 'rgba(239, 68, 68, 0.05)'];

    // 计算 MA
    const ma5 = calculateMA(closeData, 5);
    const ma10 = calculateMA(closeData, 10);

    // 成交量颜色（跟随 K 线涨跌）
    const volumeColors = filteredData.map((d, i) => {
      if (i === 0) return '#10b981';
      const prevClose = filteredData[i - 1].close || 0;
      const currClose = d.close || 0;
      return currClose >= prevClose ? '#10b981' : '#ef4444';
    });

    // 基础配置
    const baseOption: EChartsOption = {
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
          crossStyle: { color: '#999' },
        },
        backgroundColor: 'rgba(255, 255, 255, 0.95)',
        borderColor: '#e5e7eb',
        textStyle: { color: '#374151', fontSize: 12 },
        confine: true,
      },
      axisPointer: {
        link: [{ xAxisIndex: 'all' }],
        label: { backgroundColor: '#777' },
      },
      toolbox: {
        feature: {
          brush: {
            type: ['lineX', 'clear'],
            title: {
              lineX: '区间缩放',
              clear: '清除选择',
            },
          },
          dataZoom: {
            yAxisIndex: false,
            title: {
              zoom: '区域缩放',
              back: '还原',
            },
          },
          restore: {
            title: '还原',
          },
        },
        iconStyle: {
          borderColor: '#6b7280',
        },
        emphasis: {
          iconStyle: {
            borderColor: '#3b82f6',
          },
        },
        right: 10,
        top: 0,
      },
      brush: {
        xAxisIndex: 'all',
        brushLink: 'all',
        outOfBrush: { colorAlpha: 0.1 },
        brushStyle: {
          borderWidth: 1,
          color: 'rgba(59, 130, 246, 0.2)',
          borderColor: 'rgba(59, 130, 246, 0.8)',
        },
      },
      visualMap: {
        show: false,
        seriesIndex: hasVolume ? 4 : undefined, // volume series index
        dimension: 2,
        pieces: [
          { value: 1, color: '#10b981' },
          { value: -1, color: '#ef4444' },
        ],
      },
      grid: hasVolume
        ? [
            { left: '10%', right: '8%', height: '55%', top: 50 },
            { left: '10%', right: '8%', top: '75%', height: '15%' },
          ]
        : [{ left: '10%', right: '8%', bottom: '15%', top: 50 }],
      xAxis: hasVolume
        ? [
            {
              type: 'category',
              data: xData,
              boundaryGap: true,
              axisLine: { lineStyle: { color: '#e5e7eb' } },
              axisLabel: { fontSize: 10, color: '#9ca3af' },
              axisTick: { show: false },
              splitLine: { show: false },
              min: 'dataMin',
              max: 'dataMax',
              axisPointer: { z: 100 },
            },
            {
              type: 'category',
              gridIndex: 1,
              data: xData,
              boundaryGap: true,
              axisLine: { lineStyle: { color: '#e5e7eb' } },
              axisTick: { show: false },
              splitLine: { show: false },
              axisLabel: { show: false },
              min: 'dataMin',
              max: 'dataMax',
            },
          ]
        : [
            {
              type: 'category',
              data: xData,
              boundaryGap: true,
              axisLine: { lineStyle: { color: '#e5e7eb' } },
              axisLabel: { fontSize: 10, color: '#9ca3af' },
              axisTick: { show: false },
              splitLine: { show: false },
            },
          ],
      yAxis: hasVolume
        ? [
            {
              scale: true,
              splitArea: { show: true, areaStyle: { color: ['rgba(250,250,250,0.3)', 'rgba(240,240,240,0.3)'] } },
              axisLabel: { fontSize: 10, color: '#9ca3af' },
              splitLine: { lineStyle: { color: '#f3f4f6' } },
              axisLine: { show: false },
            },
            {
              scale: true,
              gridIndex: 1,
              splitNumber: 2,
              axisLabel: { show: false },
              axisLine: { show: false },
              axisTick: { show: false },
              splitLine: { show: false },
            },
          ]
        : [
            {
              type: 'value',
              scale: true,
              axisLabel: { fontSize: 10, color: '#9ca3af' },
              splitLine: { lineStyle: { color: '#f3f4f6' } },
              axisLine: { show: false },
            },
          ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: hasVolume ? [0, 1] : [0],
          start: 0,
          end: 100,
          minValueSpan: 5,
        },
        {
          show: true,
          xAxisIndex: hasVolume ? [0, 1] : [0],
          type: 'slider',
          top: hasVolume ? '92%' : '90%',
          height: 20,
          start: 0,
          end: 100,
          borderColor: '#e5e7eb',
          fillerColor: 'rgba(59, 130, 246, 0.1)',
          handleStyle: { color: '#3b82f6' },
          textStyle: { fontSize: 10, color: '#9ca3af' },
        },
      ],
      series: [],
    };

    // 根据图表类型配置 series
    const series: EChartsOption['series'] = [];

    switch (chartType) {
      case 'candlestick':
        if (hasOHLC) {
          // K 线
          series.push({
            name: '日K',
            type: 'candlestick',
            data: filteredData.map((d) => [d.open, d.close, d.low, d.high]),
            itemStyle: {
              color: '#10b981',
              color0: '#ef4444',
              borderColor: '#10b981',
              borderColor0: '#ef4444',
            },
          });
          // MA5
          series.push({
            name: 'MA5',
            type: 'line',
            data: ma5,
            smooth: true,
            symbol: 'none',
            lineStyle: { width: 1, color: '#f59e0b', opacity: 0.8 },
          });
          // MA10
          series.push({
            name: 'MA10',
            type: 'line',
            data: ma10,
            smooth: true,
            symbol: 'none',
            lineStyle: { width: 1, color: '#3b82f6', opacity: 0.8 },
          });
        } else {
          // 无 OHLC 数据时退化为折线
          series.push({
            type: 'line',
            data: closeData,
            smooth: false,
            symbol: 'none',
            lineStyle: { color: mainColor, width: 2 },
          });
        }
        break;

      case 'line':
        series.push({
          type: 'line',
          data: closeData,
          smooth: false,
          symbol: 'circle',
          symbolSize: 4,
          lineStyle: { color: mainColor, width: 2 },
          itemStyle: { color: mainColor },
        });
        break;

      case 'area':
        series.push({
          type: 'line',
          data: closeData,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: mainColor, width: 2 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: areaGradient[0] },
                { offset: 1, color: areaGradient[1] },
              ],
            },
          },
        });
        break;

      case 'mountain':
        series.push({
          type: 'line',
          data: closeData,
          smooth: 0.6,
          symbol: 'none',
          lineStyle: { color: mainColor, width: 3 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: areaGradient[0] },
                { offset: 0.5, color: areaGradient[1] },
                { offset: 1, color: 'transparent' },
              ],
            },
          },
        });
        break;
    }

    // 成交量
    if (hasVolume) {
      series.push({
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumeData.map((vol, i) => ({
          value: vol,
          itemStyle: { color: volumeColors[i] },
        })),
        barWidth: '60%',
      });
    }

    return {
      ...baseOption,
      series,
    };
  }, [filteredData, chartType, hasOHLC, hasVolume, formatTime]);

  if (loading) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4">
        <div className="h-4 bg-fin-border rounded w-24 mb-4" />
        <div className="h-[480px] bg-fin-border rounded animate-pulse" />
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-fin-card border border-fin-border rounded-xl p-4 h-[480px] flex items-center justify-center text-fin-muted text-sm">
        暂无行情数据
      </div>
    );
  }

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl p-4">
      {/* Header: 标题 + 图表类型 + 时间范围 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-fin-text">{title}</h3>
          {/* MA 图例 */}
          {chartType === 'candlestick' && hasOHLC && (
            <div className="flex items-center gap-3 text-2xs">
              <span className="flex items-center gap-1">
                <span className="w-3 h-0.5 bg-amber-500 rounded" />
                <span className="text-fin-muted">MA5</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-3 h-0.5 bg-blue-500 rounded" />
                <span className="text-fin-muted">MA10</span>
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* 图表类型切换 */}
          <div className="flex items-center bg-fin-bg rounded-lg p-1 gap-0.5">
            {CHART_TYPES.map((type) => (
              <button
                key={type.value}
                onClick={() => setChartType(type.value)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ${
                  chartType === type.value
                    ? 'bg-fin-primary text-white'
                    : 'text-fin-text-secondary hover:bg-fin-hover'
                }`}
                title={type.label}
              >
                {type.icon}
                <span className="hidden sm:inline">{type.label}</span>
              </button>
            ))}
          </div>

          {/* 时间范围选择 */}
          <div className="flex items-center bg-fin-bg rounded-lg p-1 gap-0.5">
            {TIME_RANGES.map((range) => (
              <button
                key={range.value}
                onClick={() => setTimeRange(range.value)}
                className={`px-2 py-1 rounded text-xs transition-colors ${
                  timeRange === range.value
                    ? 'bg-fin-primary text-white'
                    : 'text-fin-text-secondary hover:bg-fin-hover'
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 图表区域 */}
      <div className="h-[480px]">
        {option ? (
          <ReactECharts
            option={option}
            style={{ height: '100%', width: '100%' }}
            opts={{ renderer: 'canvas' }}
            notMerge={true}
          />
        ) : (
          <div className="h-full flex items-center justify-center text-fin-muted text-sm">
            所选时间范围内无数据
          </div>
        )}
      </div>

      {/* 底部说明 */}
      <div className="mt-2 text-2xs text-fin-muted text-center">
        使用工具栏进行区间缩放 · 滚轮缩放 · 拖动底部滑块 · 双击还原
      </div>
    </div>
  );
}

export default MarketChartCard;

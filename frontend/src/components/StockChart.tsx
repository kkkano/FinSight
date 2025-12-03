import React, { useEffect, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { useStore } from '../store/useStore';
import { apiClient } from '../api/client';
import type { KlineData } from '../types/index';
import { Loader2, BarChart3, TrendingUp, Activity } from 'lucide-react';

// 时间周期选项
const PERIOD_OPTIONS = [
  { value: '5d', label: '24小时', interval: '1h', period: '5d' }, // 日线改为24小时，使用5d获取数据但显示为24小时
  { value: '1mo', label: '1月', interval: '1d', period: '1mo' },
  { value: '3mo', label: '3月', interval: '1d', period: '3mo' },
  { value: '6mo', label: '6月', interval: '1d', period: '6mo' },
  { value: '1y', label: '1年', interval: '1d', period: '1y' },
  { value: '2y', label: '2年', interval: '1wk', period: '2y' },
  { value: '5y', label: '5年', interval: '1mo', period: '5y' },
  { value: 'max', label: '全部', interval: '1mo', period: 'max' },
];

// 图表类型
type ChartType = 'candlestick' | 'line';

export const StockChart: React.FC = () => {
  const { currentTicker } = useStore();
  const [data, setData] = useState<KlineData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState('5d'); // 默认显示24小时
  const [chartType, setChartType] = useState<ChartType>('candlestick');
  const [isMockData, setIsMockData] = useState(false);

  // 根据周期获取对应的 interval 和实际 period
  const getPeriodConfig = (periodValue: string): { interval: string; period: string } => {
    const option = PERIOD_OPTIONS.find(opt => opt.value === periodValue);
    if (option) {
      return { interval: option.interval, period: option.period || option.value };
    }
    // 对于"24小时"，使用5d获取数据，但interval用1d（因为yfinance可能不支持1h）
    if (periodValue === '5d') {
      return { interval: '1d', period: '5d' }; // 获取5天数据，显示最近24小时
    }
    return { interval: '1d', period: periodValue };
  };

  useEffect(() => {
    if (!currentTicker) return;

    const loadData = async () => {
      setLoading(true);
      setError(null);
      setIsMockData(false);
      
      try {
        const { interval, period: actualPeriod } = getPeriodConfig(period);
        const res = await apiClient.fetchKline(currentTicker, actualPeriod, interval);
        
        // apiClient.fetchKline 返回的是 response.data，即后端返回的完整数据
        // 后端返回格式: {ticker: string, data: {kline_data: [...] 或 error: "..."}, cached: boolean}
        console.log('[StockChart] 收到数据:', res);
        
        // 检查响应结构
        if (res && res.data) {
          const responseData = res.data;
          
          // 检查是否有错误
          if (responseData.error) {
            console.error('[StockChart] 后端返回错误:', responseData.error);
            setError(responseData.error);
            setData(generateMockData(currentTicker, period));
            setIsMockData(true);
          } 
          // 检查是否有 kline_data
          else if (responseData.kline_data && Array.isArray(responseData.kline_data) && responseData.kline_data.length > 0) {
            console.log(`[StockChart] ✅ 成功获取 ${responseData.kline_data.length} 条真实数据 (来源: ${responseData.source || 'unknown'})`);
            let processedData = responseData.kline_data;
            
            // 如果是"24小时"视图，只显示最近24小时的数据
            if (period === '5d') {
              const now = new Date().getTime();
              const oneDayAgo = now - 24 * 60 * 60 * 1000;
              processedData = responseData.kline_data.filter((item: KlineData) => {
                const itemTime = new Date(item.time).getTime();
                return itemTime >= oneDayAgo;
              });
              // 如果过滤后数据太少，至少保留最近的数据点
              if (processedData.length < 10 && responseData.kline_data.length > 0) {
                processedData = responseData.kline_data.slice(-24); // 保留最后24个数据点
              }
            }
            
            setData(processedData);
            setIsMockData(false);
            setError(null); // 清除错误
          } 
          // 数据为空
          else {
            console.warn('[StockChart] 数据为空或格式错误:', responseData);
            setError('数据为空');
            setData(generateMockData(currentTicker, period));
            setIsMockData(true);
          }
        } else {
          console.error('[StockChart] 响应格式错误:', res);
          setError('无法获取数据：响应格式错误');
          setData(generateMockData(currentTicker, period));
          setIsMockData(true);
        }
      } catch (err: any) {
        console.error('[StockChart] K线数据加载错误:', err);
        setError(err.message || '无法加载图表数据');
        setData(generateMockData(currentTicker, period));
        setIsMockData(true);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [currentTicker, period]);

  if (!currentTicker) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-fin-muted space-y-4 animate-fade-in">
        <div className="p-4 bg-fin-panel rounded-full">
          <BarChart3 size={48} className="opacity-50" />
        </div>
        <p>在左侧对话框询问股票代码 (如 "AAPL")<br/>即可在此处查看实时图表</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-fin-primary animate-pulse">
        <Loader2 className="animate-spin mr-2" />
        正在加载 {currentTicker} 数据...
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-trend-down">
        {error || '暂无数据'}
      </div>
    );
  }

  // 计算涨跌百分比数据（用于折线图）
  const calculateReturns = (data: KlineData[]): Array<{time: string, value: number}> => {
    if (data.length === 0) return [];
    
    const firstClose = data[0].close;
    return data.map(item => ({
      time: item.time,
      value: ((item.close - firstClose) / firstClose) * 100
    }));
  };

  const returnsData = calculateReturns(data);

  // ECharts 配置 - K线图
  const candlestickOption = {
    backgroundColor: 'transparent',
    title: {
      text: `${currentTicker} ${PERIOD_OPTIONS.find(opt => opt.value === period)?.label || period}`,
      left: 'center',
      textStyle: { color: '#e4e4e7', fontSize: 14 }
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { 
        type: 'cross',
        lineStyle: { color: '#3b82f6', width: 1, type: 'dashed' },
        crossStyle: { color: '#3b82f6', width: 1, type: 'dashed' }
      },
      backgroundColor: 'rgba(24, 24, 27, 0.95)',
      borderColor: '#3b82f6',
      borderWidth: 1,
      textStyle: { color: '#e4e4e7', fontSize: 12 },
      padding: [10, 12],
      formatter: (params: any) => {
        const data = params[0];
        const open = parseFloat(data.data[1]).toFixed(2);
        const close = parseFloat(data.data[2]).toFixed(2);
        const high = parseFloat(data.data[3]).toFixed(2);
        const low = parseFloat(data.data[4]).toFixed(2);
        const change = parseFloat(close) - parseFloat(open);
        const changePercent = ((change / parseFloat(open)) * 100).toFixed(2);
        const changeColor = change >= 0 ? '#22c55e' : '#ef4444';
        
        // 格式化时间显示（24小时视图）
        let timeDisplay = data.axisValue;
        if (period === '5d' && data.axisValue) {
          // 如果已经是时间格式（HH:MM），直接使用；否则尝试转换
          if (!data.axisValue.includes(':')) {
            try {
              const date = new Date(data.axisValue);
              timeDisplay = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
            } catch (e) {
              timeDisplay = data.axisValue;
            }
          }
        }
        
        return `
          <div style="padding: 4px;">
            <div style="font-weight: 600; margin-bottom: 6px; color: #f4f4f5;">${timeDisplay}</div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
              <span style="color: #a1a1aa;">开盘:</span>
              <span style="color: #e4e4e7; font-weight: 500;">$${open}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
              <span style="color: #a1a1aa;">收盘:</span>
              <span style="color: ${changeColor}; font-weight: 600;">$${close}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
              <span style="color: #a1a1aa;">最高:</span>
              <span style="color: #e4e4e7; font-weight: 500;">$${high}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
              <span style="color: #a1a1aa;">最低:</span>
              <span style="color: #e4e4e7; font-weight: 500;">$${low}</span>
            </div>
            <div style="margin-top: 6px; padding-top: 6px; border-top: 1px solid #27272a;">
              <span style="color: ${changeColor}; font-weight: 600;">
                ${change >= 0 ? '+' : ''}${change.toFixed(2)} (${changePercent}%)
              </span>
            </div>
          </div>
        `;
      }
    },
    grid: {
      left: '3%',
      right: '3%',
      bottom: '15%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: data.map(item => {
        // 如果是24小时视图，显示时间；否则显示日期
        if (period === '5d') {
          const date = new Date(item.time);
          return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        }
        return item.time;
      }),
      axisLine: { lineStyle: { color: '#27272a' } },
      axisLabel: { 
        color: '#a1a1aa', 
        rotate: period === '5d' ? 0 : 45,
        fontSize: period === '5d' ? 10 : 12
      }
    },
    yAxis: {
      scale: true,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#27272a' } },
      axisLabel: { color: '#a1a1aa', formatter: '${value}' }
    },
    dataZoom: [
      { type: 'inside', start: 50, end: 100 },
      { type: 'slider', show: true, bottom: '5%', height: 20 }
    ],
    series: [
      {
        type: 'candlestick',
        name: 'K线',
        data: data.map(item => [item.open, item.close, item.low, item.high]),
        itemStyle: {
          color: '#22c55e',        // 涨 (绿)
          color0: '#ef4444',       // 跌 (红)
          borderColor: '#22c55e',
          borderColor0: '#ef4444'
        }
      }
    ]
  };

  // ECharts 配置 - 折线图（涨跌趋势）
  const lineOption = {
    backgroundColor: 'transparent',
    title: {
      text: `${currentTicker} 涨跌趋势 (相对起始点)`,
      left: 'center',
      textStyle: { color: '#e4e4e7', fontSize: 14 }
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(24, 24, 27, 0.9)',
      borderColor: '#27272a',
      textStyle: { color: '#e4e4e7' },
      formatter: (params: any) => {
        const data = params[0];
        const sign = data.value >= 0 ? '+' : '';
        return `
          <div style="padding: 8px;">
            <div><strong>${data.axisValue}</strong></div>
            <div>涨跌: <span style="color: ${data.value >= 0 ? '#22c55e' : '#ef4444'}">${sign}${data.value.toFixed(2)}%</span></div>
          </div>
        `;
      }
    },
    grid: {
      left: '3%',
      right: '3%',
      bottom: '15%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: returnsData.map(item => {
        // 如果是24小时视图，显示时间；否则显示日期
        if (period === '5d') {
          const date = new Date(item.time);
          return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        }
        return item.time;
      }),
      axisLine: { lineStyle: { color: '#27272a' } },
      axisLabel: { 
        color: '#a1a1aa', 
        rotate: period === '5d' ? 0 : 45,
        fontSize: period === '5d' ? 10 : 12
      }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#27272a' } },
      axisLabel: { 
        color: '#a1a1aa', 
        formatter: (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
      }
    },
    dataZoom: [
      { type: 'inside', start: 50, end: 100 },
      { type: 'slider', show: true, bottom: '5%', height: 20 }
    ],
    series: [
      {
        type: 'line',
        name: '涨跌',
        data: returnsData.map(item => item.value),
        smooth: true,
        lineStyle: {
          color: '#3b82f6',
          width: 2
        },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
              { offset: 1, color: 'rgba(59, 130, 246, 0.05)' }
            ]
          }
        },
        itemStyle: {
          color: '#3b82f6'
        }
      }
    ]
  };

  const option = chartType === 'candlestick' ? candlestickOption : lineOption;

  return (
    <div className="h-full w-full flex flex-col animate-slide-up">
      {/* 控制栏 */}
      <div className="flex items-center justify-between p-2 border-b border-fin-border bg-fin-panel">
        {/* 时间周期选择 */}
        <div className="flex gap-1">
          {PERIOD_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setPeriod(opt.value)}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                period === opt.value
                  ? 'bg-fin-primary text-white'
                  : 'bg-fin-bg text-fin-muted hover:bg-fin-border'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* 图表类型切换 */}
        <div className="flex gap-2">
          <button
            onClick={() => setChartType('candlestick')}
            className={`p-1.5 rounded transition-colors ${
              chartType === 'candlestick'
                ? 'bg-fin-primary text-white'
                : 'text-fin-muted hover:bg-fin-border'
            }`}
            title="K线图"
          >
            <Activity size={16} />
          </button>
          <button
            onClick={() => setChartType('line')}
            className={`p-1.5 rounded transition-colors ${
              chartType === 'line'
                ? 'bg-fin-primary text-white'
                : 'text-fin-muted hover:bg-fin-border'
            }`}
            title="涨跌趋势图"
          >
            <TrendingUp size={16} />
          </button>
        </div>
      </div>

      {/* 警告信息 */}
      {isMockData && error && (
        <div className="p-2 bg-yellow-500/10 border-b border-yellow-500/20 text-yellow-500 text-xs">
          ⚠️ {error} (显示模拟数据)
        </div>
      )}

      {/* 图表 */}
      <div className="flex-1 p-4">
        <ReactECharts option={option} style={{ height: '100%', width: '100%' }} />
      </div>
    </div>
  );
};

// 生成模拟 K 线数据（作为回退方案）
const generateMockData = (_ticker: string, period: string = '1y'): KlineData[] => {
  const data: KlineData[] = [];
  const today = new Date();
  const basePrice = 100;
  
  // 根据周期确定数据点数量
  const periodDays: Record<string, number> = {
    '1d': 1,
    '5d': 5,
    '1mo': 30,
    '3mo': 90,
    '6mo': 180,
    '1y': 252,
    '2y': 504,
    '5y': 1260,
    'max': 2520
  };
  
  const days = periodDays[period] || 252;
  
  for (let i = days - 1; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    
    if (date.getDay() === 0 || date.getDay() === 6) continue;
    
    const change = (Math.random() - 0.5) * 10;
    const open = basePrice + change;
    const close = open + (Math.random() - 0.5) * 5;
    const high = Math.max(open, close) + Math.random() * 3;
    const low = Math.min(open, close) - Math.random() * 3;
    
    data.push({
      time: date.toISOString().split('T')[0],
      open: Math.round(open * 100) / 100,
      high: Math.round(high * 100) / 100,
      low: Math.round(low * 100) / 100,
      close: Math.round(close * 100) / 100,
    });
  }
  
  return data;
};

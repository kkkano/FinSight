import React, { useEffect, useRef, useState } from 'react';
import { useStore } from '../store/useStore';
import ReactMarkdown from 'react-markdown';
import { Bot, User } from 'lucide-react';
import clsx from 'clsx';
import { InlineChart } from './InlineChart';
import { ThinkingProcess } from './ThinkingProcess';
import { apiClient } from '../api/client';
import type { KlineData, ChartType } from '../types/index';

export const ChatList: React.FC = () => {
  const { messages, isChatLoading, statusMessage, statusSince } = useStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [elapsed, setElapsed] = useState<string>('0.0');

  // 只滚动聊天容器本身，避免整页被拉走
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.scrollTo({
      top: container.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, isChatLoading]);

  // 动态计时
  useEffect(() => {
    if (!statusSince) {
      setElapsed('0.0');
      return;
    }
    const timer = setInterval(() => {
      const delta = (Date.now() - statusSince) / 1000;
      setElapsed(delta.toFixed(1));
    }, 200);
    return () => clearInterval(timer);
  }, [statusSince]);

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8 space-y-6"
    >
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={clsx(
            "flex w-full animate-slide-up",
            msg.role === 'user' ? "justify-end" : "justify-start"
          )}
        >
          <div className={clsx(
            "flex max-w-[85%] md:max-w-[75%] lg:max-w-[65%] xl:max-w-[55%]",
            msg.role === 'user' ? "flex-row-reverse" : "flex-row"
          )}>
            {/* 头像 */}
            <div className={clsx(
              "flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2",
              msg.role === 'user' ? "bg-fin-primary text-white" : "bg-fin-panel border border-fin-border text-fin-primary"
            )}>
              {msg.role === 'user' ? <User size={16} /> : <Bot size={16} />}
            </div>

            {/* 气泡 */}
            <div className={clsx(
              "p-3 rounded-2xl text-sm leading-relaxed shadow-sm",
              msg.role === 'user' 
                ? "bg-fin-primary text-white rounded-tr-none" 
                : "bg-fin-panel border border-fin-border text-fin-text rounded-tl-none"
            )}>
              {msg.role === 'user' ? (
                msg.content
              ) : (
                <>
                  <MessageWithChart content={msg.content} />
                  {msg.data_origin && (
                    <div className="mt-2 text-[11px] text-fin-muted flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded-full border border-fin-border/60 bg-fin-bg/60">
                        来源: {msg.data_origin} {msg.fallback_used ? '(兜底)' : ''}
                      </span>
                      {msg.as_of && <span className="px-2 py-0.5 rounded-full border border-fin-border/60 bg-fin-bg/60">截至: {msg.as_of}</span>}
                      {msg.tried_sources && msg.tried_sources.length > 0 && (
                        <span className="text-[10px] text-fin-muted/70">
                          尝试: {msg.tried_sources.join(' → ')}
                        </span>
                      )}
                    </div>
                  )}
                  {msg.thinking && msg.thinking.length > 0 && (
                    <ThinkingProcess thinking={msg.thinking} />
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      ))}

      {/* Loading Indicator */}
      {isChatLoading && (
        <div className="flex w-full justify-start animate-fade-in">
          <div className="flex flex-row items-center ml-12 rounded-xl border border-fin-border/60 bg-fin-panel/60 px-3 py-2 gap-2 shadow-sm">
            <div className="flex space-x-1">
              <div className="w-2 h-2 bg-fin-muted rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <div className="w-2 h-2 bg-fin-muted rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <div className="w-2 h-2 bg-fin-muted rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
            <span className="text-xs text-fin-muted">
              {statusMessage || 'Analyzing...'}（用时 {elapsed}s）
            </span>
          </div>
        </div>
      )}
      
      <div ref={messagesEndRef} />
    </div>
  );
};

// 支持图表的消息组件
const MessageWithChart: React.FC<{ content: string }> = ({ content }) => {
  const [chartData, setChartData] = useState<{ ticker: string; chartType: ChartType; summary: string } | null>(null);
  
  useEffect(() => {
    // 检测图表标记 [CHART:TICKER:TYPE] - 支持所有图表类型
    const chartMatch = content.match(/\[CHART:([A-Z]+):([a-z]+)\]/);
    if (chartMatch) {
      const [, ticker, chartTypeStr] = chartMatch;
      // 确保 chartType 是有效的 ChartType
      const validChartTypes: ChartType[] = ['line', 'candlestick', 'pie', 'bar', 'tree', 'area', 'scatter', 'heatmap'];
      const chartType = (validChartTypes.includes(chartTypeStr as ChartType) ? chartTypeStr : 'line') as ChartType;
      setChartData({ 
        ticker, 
        chartType: chartType,
        summary: '' 
      });
    }
  }, [content]);

  // 处理图表数据就绪回调，将数据摘要加入消息内容
  const handleChartDataReady = (_data: KlineData[], summary: string) => {
    if (chartData) {
      setChartData({ ...chartData, summary });
      // 将数据摘要发送到后端，加入聊天历史
      sendChartDataToBackend(chartData.ticker, summary);
    }
  };

  // 发送图表数据到后端，加入聊天历史
  const sendChartDataToBackend = async (ticker: string, summary: string) => {
    try {
      await apiClient.addChartData(ticker, summary);
      console.log(`[图表数据] ${ticker} 数据摘要已加入聊天上下文，可供AI分析`);
    } catch (err) {
      console.error('发送图表数据失败:', err);
    }
  };

  // 移除图表标记后的纯文本内容
  const textContent = content.replace(/\[CHART:[^\]]+\]/g, '');

  return (
    <div className="prose prose-invert prose-sm max-w-none">
      <ReactMarkdown>{textContent}</ReactMarkdown>
      {chartData && (
        <InlineChart 
          ticker={chartData.ticker}
          chartType={chartData.chartType}
          onDataReady={handleChartDataReady}
        />
      )}
    </div>
  );
};

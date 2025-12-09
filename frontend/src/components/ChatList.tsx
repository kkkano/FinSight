import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Bot, User, Copy, RefreshCcw, Trash2, Download } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';
import clsx from 'clsx';
import { InlineChart } from './InlineChart';
import { ThinkingProcess } from './ThinkingProcess';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
import type { KlineData, ChartType } from '../types/index';

const chartKeywords = ['trend', 'chart', 'kline', 'k-line', '走势', '趋势', '图表'];

const shouldGenerateChart = async (
  query: string,
  currentTicker?: string | null,
): Promise<{ ticker: string | null; chartType: string | null }> => {
  try {
    const response = await apiClient.detectChartType(query, currentTicker || undefined);

    if (response.success && response.should_generate) {
      const ticker = extractTicker(query) ?? currentTicker ?? null;
      return {
        ticker,
        chartType: response.chart_type || 'line',
      };
    }
  } catch (error) {
    console.error('Chart detection failed:', error);
  }

  const lowerQuery = query.toLowerCase();
  const hasChartKeyword = chartKeywords.some((keyword) => lowerQuery.includes(keyword));
  if (!hasChartKeyword) return { ticker: null, chartType: null };

  const ticker = extractTicker(query) ?? currentTicker ?? null;
  return { ticker, chartType: 'line' };
};

const extractTicker = (text: string): string | null => {
  const tickerPattern = /\b([A-Z]{1,5})\b/g;
  const matches = text.match(tickerPattern);
  return matches && matches.length > 0 ? matches[0] : null;
};

export const ChatList: React.FC = () => {
  const { messages, isChatLoading, statusMessage, statusSince, removeMessage, setStatus, setLoading, setTicker, addMessage, updateMessage } = useStore();
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

  const findNearestUserQuery = (index: number): string | null => {
    const before = [...messages.slice(0, index)].reverse().find((m) => m.role === 'user');
    if (before?.content?.trim()) return before.content.trim();
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    return lastUser?.content?.trim() || null;
  };

  const handleRetry = async (messageId: string) => {
    if (isChatLoading) return;

    const idx = messages.findIndex((m) => m.id === messageId);
    if (idx === -1) return;
    const originalMsg = messages[idx];
    const query = findNearestUserQuery(idx);
    if (!query) {
      setStatus('No user query found to retry');
      setTimeout(() => setStatus(null), 1500);
      return;
    }

    setLoading(true);
    setStatus('Retrying request...');
    updateMessage(messageId, { isLoading: true, content: '' });

    try {
      const response = await apiClient.sendMessage(query);

      const chartInfo = await shouldGenerateChart(query, response.current_focus ?? null);
      const tickerToChart = chartInfo.ticker || null;

      let responseContent = response.response;
      if (tickerToChart && chartInfo.chartType) {
        responseContent += `\n\n[CHART:${tickerToChart}:${chartInfo.chartType}]`;
      }

      updateMessage(messageId, {
        content: responseContent,
        timestamp: Date.now(),
        intent: response.intent,
        relatedTicker: response.current_focus || tickerToChart || undefined,
        thinking: response.thinking,
        data_origin: response.data?.data_origin,
        as_of: response.data?.as_of ?? null,
        fallback_used: response.data?.fallback_used,
        tried_sources: response.data?.tried_sources,
        isLoading: false,
      });

      const elapsedSeconds =
        (response.thinking_elapsed_seconds ?? response.response_time_ms / 1000).toFixed(1);
      setStatus(`Completed in ${elapsedSeconds}s`);

      if (response.current_focus || tickerToChart) {
        setTicker(response.current_focus || tickerToChart);
      }
    } catch (error) {
      updateMessage(messageId, {
        content: originalMsg.content,
        isLoading: false,
      });
      addMessage({
        id: uuidv4(),
        role: 'system',
        content: 'Retry failed. Please confirm the backend service is running.',
        timestamp: Date.now(),
      });
      setStatus('Retry failed');
    } finally {
      setLoading(false);
      setTimeout(() => setStatus(null), 2000);
    }
  };

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
                : "bg-fin-panel border border-fin-border text-fin-text rounded-tl-none relative overflow-visible"
            )}>
              {msg.role === 'user' ? (
                msg.content
              ) : (
                <>
                  {msg.isLoading ? (
                    <div className="py-4 flex items-center justify-start">
                      <LoadingDots />
                    </div>
                  ) : (
                    <MessageWithChart content={msg.content} />
                  )}
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
                  <MessageActions
                    messageId={msg.id}
                    content={msg.content}
                    onRetry={() => handleRetry(msg.id)}
                    onDelete={() => removeMessage(msg.id)}
                  />
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
      <ReactMarkdown
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              className="text-blue-400 underline hover:text-blue-300"
              target="_blank"
              rel="noreferrer"
            >
              {children}
            </a>
          ),
        }}
      >
        {textContent}
      </ReactMarkdown>
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

const MessageActions: React.FC<{
  messageId: string;
  content: string;
  onRetry: () => void;
  onDelete: () => void;
}> = ({ content, onRetry, onDelete }) => {
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
    } catch (e) {
      console.error('Copy failed', e);
    }
  };

  const handleExport = () => {
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'message.md';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="absolute bottom-0 right-2 translate-y-full flex items-center gap-3 text-fin-muted pointer-events-auto">
      <button
        className="p-1 rounded hover:text-fin-text"
        title="复制"
        onClick={handleCopy}
      >
        <Copy size={14} />
      </button>
      <button
        className="p-1 rounded hover:text-fin-text"
        title="重试"
        onClick={onRetry}
      >
        <RefreshCcw size={14} />
      </button>
      <button
        className="p-1 rounded hover:text-fin-text"
        title="导出"
        onClick={handleExport}
      >
        <Download size={14} />
      </button>
      <button
        className="p-1 rounded hover:text-fin-text"
        title="删除"
        onClick={onDelete}
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
};

const LoadingDots: React.FC = () => (
  <div className="flex space-x-2">
    <span className="w-2 h-2 rounded-full bg-fin-muted animate-bounce" style={{ animationDelay: '0ms' }} />
    <span className="w-2 h-2 rounded-full bg-fin-muted animate-bounce" style={{ animationDelay: '150ms' }} />
    <span className="w-2 h-2 rounded-full bg-fin-muted animate-bounce" style={{ animationDelay: '300ms' }} />
  </div>
);

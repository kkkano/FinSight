import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User, Copy, RefreshCcw, Trash2, Download, ExternalLink, Link2 } from 'lucide-react';
import { normalizeMarkdown } from '../utils/markdown';
import { v4 as uuidv4 } from 'uuid';
import clsx from 'clsx';
import { InlineChart } from './InlineChart';
import { SmartChartRenderer, parseSmartChartBlocks, stripSmartChartTags } from './SmartChart';
import { ThinkingProcess } from './thinking';
import { ReportView } from './report';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
import type { ChartType, ThinkingStep, ReportIR, EvidenceItem } from '../types/index';

const chartKeywords = ['trend', 'chart', 'kline', 'k-line', '走势', '趋势', '图表'];
const STOPPED_GENERATION_MESSAGE = '已停止生成，保留已完成的结果。';

// InlineChart 唯一数据源是 K 线（fetchKline），只能真实渲染以下类型。
// 其余类型（pie/bar/radar/gauge/scatter...）若强行注入会被画成股价折线，
// 造成"标题说营收构成、图画股价"的错配，因此诚实跳过。
const INLINE_RENDERABLE_TYPES = new Set(['line', 'candlestick', 'area']);
// 仅 K 线 / 技术取数方式能被 InlineChart 真出图。
const INLINE_RENDERABLE_DATA_KINDS = new Set(['kline', 'technical']);

// 决定 chart_type + data_kind 是否能被 InlineChart 诚实地真出图。
const isInlineChartRenderable = (
  chartType: string | null,
  dataKind: string | null,
): boolean => {
  if (!chartType) return false;
  if (!INLINE_RENDERABLE_TYPES.has(chartType)) return false;
  // data_kind 缺省（如旧后端 / 关键词回退未给）时，按类型保守放行 line/candlestick/area。
  if (!dataKind) return true;
  return INLINE_RENDERABLE_DATA_KINDS.has(dataKind);
};

const shouldGenerateChart = async (
  query: string,
  currentTicker?: string | null,
): Promise<{ tickers: string[]; chartType: string | null }> => {
  try {
    const response = await apiClient.detectChartType(query, currentTicker || undefined);
    const apiCandidates = Array.isArray(response?.ticker_candidates)
      ? response.ticker_candidates.map((value: unknown) => String(value))
      : [];
    const resolvedTicker = typeof response?.resolved_ticker === 'string' && response.resolved_ticker.trim()
      ? [response.resolved_ticker]
      : [];
    const localCandidates = extractTickers(query);
    const contextual = currentTicker ? [currentTicker] : [];
    const merged = mergeTickerCandidates(apiCandidates, resolvedTicker, localCandidates, contextual);

    if (response.success && response.should_generate) {
      const chartType = response.chart_type || 'line';
      const dataKind = typeof response.data_kind === 'string' ? response.data_kind : null;
      // 诚实原则：只在 InlineChart 能真出图时注入图表标记，否则跳过（chartType=null）。
      if (isInlineChartRenderable(chartType, dataKind)) {
        return { tickers: merged, chartType };
      }
      return { tickers: merged, chartType: null };
    }
  } catch {
    console.error('Chart detection failed');
  }

  const lowerQuery = query.toLowerCase();
  const hasChartKeyword = chartKeywords.some((keyword) => lowerQuery.includes(keyword));
  if (!hasChartKeyword) return { tickers: [], chartType: null };

  const localCandidates = extractTickers(query);
  const contextual = currentTicker ? [currentTicker] : [];
  return { tickers: mergeTickerCandidates(localCandidates, contextual), chartType: 'line' };
};

const TICKER_STOPWORDS = new Set([
  'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'CEO', 'IPO', 'ETF', 'VS',
  'PE', 'EPS', 'MACD', 'RSI', 'KDJ', 'GDP', 'CPI', 'PPI', 'FOMC',
  'WITH', 'VIEW', 'FROM', 'FOR', 'OVER', 'NEWS', 'WHAT', 'WHEN', 'WHERE',
  'WHY', 'THIS', 'THAT', 'THE', 'AND', 'ARE', 'WAS', 'WERE',
]);

const MAX_AUTO_CHART_TICKERS = 3;
const TICKER_PATTERN = /^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/;

const mergeTickerCandidates = (...sources: Array<string[] | undefined>): string[] => {
  const merged: string[] = [];
  const seen = new Set<string>();
  for (const source of sources) {
    for (const raw of source ?? []) {
      const ticker = String(raw || '').trim().toUpperCase();
      if (!ticker || seen.has(ticker)) continue;
      if (TICKER_STOPWORDS.has(ticker)) continue;
      if (!TICKER_PATTERN.test(ticker)) continue;
      seen.add(ticker);
      merged.push(ticker);
      if (merged.length >= MAX_AUTO_CHART_TICKERS) return merged;
    }
  }
  return merged;
};

const extractTickers = (text: string): string[] => {
  if (!text || !text.trim()) return [];

  const seen = new Set<string>();
  const tickers: string[] = [];
  const addTicker = (raw: string) => {
    const symbol = String(raw || '').trim().toUpperCase();
    if (!symbol || seen.has(symbol)) return;
    if (symbol.length > 20 || /\s/.test(symbol)) return;
    seen.add(symbol);
    tickers.push(symbol);
  };

  for (const match of text.matchAll(/\^([A-Za-z]{1,8})\b/g)) {
    addTicker(`^${match[1]}`);
  }
  for (const match of text.matchAll(/\b(\d{5,6}\.(?:SS|SZ|BJ|HK))\b/gi)) {
    addTicker(match[1]);
  }
  for (const match of text.matchAll(/\b([A-Za-z]{1,8}-[A-Za-z]{2,5})\b/g)) {
    addTicker(match[1]);
  }
  for (const match of text.matchAll(/\b([A-Za-z]{1,4}=F)\b/g)) {
    addTicker(match[1]);
  }
  for (const match of text.matchAll(/\$([A-Za-z]{1,6})\b/g)) {
    addTicker(match[1]);
  }
  for (const match of text.matchAll(/\b([A-Za-z]{1,6}[.-][A-Za-z]{1,4})\b/g)) {
    addTicker(match[1]);
  }

  const alphaTokens = text.match(/\b[A-Za-z]{1,6}\b/g) ?? [];
  for (const token of alphaTokens) {
    if (token !== token.toUpperCase()) continue;
    const upper = token.toUpperCase();
    if (TICKER_STOPWORDS.has(upper)) continue;
    addTicker(upper);
  }

  return tickers.slice(0, MAX_AUTO_CHART_TICKERS);
};

// ── Shared sub-components ──

const EvidenceSection: React.FC<{ evidence_pool: EvidenceItem[] }> = ({ evidence_pool }) => (
  <div className="mt-3 rounded-lg border border-fin-border/60 bg-fin-bg/40 px-3 py-2">
    <div className="text-[11px] text-fin-muted mb-2">Evidence ({evidence_pool.length})</div>
    <div className="flex flex-wrap gap-2">
      {evidence_pool.map((ev, idx) => {
        const label = ev.title || ev.source || ev.url || `Source ${idx + 1}`;
        if (ev.url) {
          return <SourceLink key={`${ev.url}-${idx}`} href={ev.url} label={label} />;
        }
        return (
          <span key={`ev-${idx}`} className="px-2 py-1 rounded-full border border-fin-border/70 bg-fin-panel text-[11px] text-fin-text">
            {label}
          </span>
        );
      })}
    </div>
  </div>
);

const DataOriginTag: React.FC<{ data_origin?: string; fallback_used?: boolean; as_of?: string | null; tried_sources?: string[] }> = ({
  data_origin, fallback_used, as_of, tried_sources,
}) => {
  if (!data_origin) return null;
  return (
    <div className="mt-2 text-[11px] text-fin-muted flex items-center gap-2">
      <span className="px-2 py-0.5 rounded-full border border-fin-border/60 bg-fin-bg/60">
        来源: {data_origin} {fallback_used ? '(兜底)' : ''}
      </span>
      {as_of && <span className="px-2 py-0.5 rounded-full border border-fin-border/60 bg-fin-bg/60">截至: {as_of}</span>}
      {tried_sources && tried_sources.length > 0 && (
        <span className="text-2xs text-fin-muted/70">尝试: {tried_sources.join(' → ')}</span>
      )}
    </div>
  );
};

type MessagePayload = {
  id: string;
  role: string;
  content: string;
  isLoading?: boolean;
  report?: ReportIR;
  evidence_pool?: EvidenceItem[];
  data_origin?: string;
  fallback_used?: boolean;
  as_of?: string | null;
  tried_sources?: string[];
  thinking?: ThinkingStep[];
};

const AssistantContent: React.FC<{
  msg: MessagePayload;
  onRetry: () => void;
  onDelete: () => void;
  actionsInline?: boolean;
}> = ({ msg, onRetry, onDelete, actionsInline }) => (
  <>
    {msg.isLoading ? (
      msg.content ? (
        <MessageWithChart content={msg.content} />
      ) : (
        <div className="py-4 flex items-center justify-start">
          <LoadingDots />
        </div>
      )
    ) : msg.report ? (
      <ReportView report={msg.report} />
    ) : (
      <MessageWithChart content={msg.content} />
    )}
    {msg.evidence_pool && msg.evidence_pool.length > 0 && (
      <EvidenceSection evidence_pool={msg.evidence_pool} />
    )}
    <DataOriginTag
      data_origin={msg.data_origin}
      fallback_used={msg.fallback_used}
      as_of={msg.as_of}
      tried_sources={msg.tried_sources}
    />
    {msg.thinking && msg.thinking.length > 0 && (
      <ThinkingProcess thinking={msg.thinking} />
    )}
    <MessageActions
      messageId={msg.id}
      content={msg.content}
      thinking={msg.thinking}
      report={msg.report}
      onRetry={onRetry}
      onDelete={onDelete}
      inline={actionsInline}
    />
  </>
);

// ── Avatar ──

const Avatar: React.FC<{ role: string; size?: number }> = ({ role, size = 32 }) => {
  const iconSize = Math.round(size * 0.5);
  return (
    <div
      className={clsx(
        "flex-shrink-0 rounded-full flex items-center justify-center",
        role === 'user' ? "bg-fin-primary text-white" : "bg-fin-panel border border-fin-border text-fin-primary"
      )}
      style={{ width: size, height: size }}
    >
      {role === 'user' ? <User size={iconSize} /> : <Bot size={iconSize} />}
    </div>
  );
};

// ── Bubble Message (original layout) ──

const BubbleMessage: React.FC<{
  msg: MessagePayload;
  onRetry: () => void;
  onDelete: () => void;
}> = ({ msg, onRetry, onDelete }) => (
  <div className={clsx("flex w-full animate-slide-up", msg.role === 'user' ? "justify-end" : "justify-start")}>
    <div className={clsx(
      "flex",
      msg.role === 'user'
        ? "max-w-[85%] md:max-w-[72%] lg:max-w-[60%] flex-row-reverse"
        : "max-w-[97%] lg:max-w-[90%] xl:max-w-[82%] flex-row"
    )}>
      <div className="mx-2"><Avatar role={msg.role} /></div>
      <div className={clsx(
        "p-4 rounded-xl text-sm leading-relaxed shadow-sm",
        msg.role === 'user'
          ? "bg-fin-hover text-fin-text rounded-tr-sm"
          : "bg-fin-panel border border-fin-border text-fin-text rounded-tl-sm relative overflow-visible"
      )}>
        {msg.role === 'user' ? (
          msg.content
        ) : (
          <AssistantContent msg={msg} onRetry={onRetry} onDelete={onDelete} />
        )}
      </div>
    </div>
  </div>
);

// ── Flat Message (ChatGPT-style layout) ──

const FlatMessage: React.FC<{
  msg: MessagePayload;
  onRetry: () => void;
  onDelete: () => void;
}> = ({ msg, onRetry, onDelete }) => {
  const isUser = msg.role === 'user';
  return (
    <div className="group/msg animate-slide-up">
      <div className={clsx("py-6 px-4 md:px-6", isUser ? "bg-transparent" : "bg-transparent")}>
        <div className="max-w-[48rem] mx-auto flex gap-4">
          {/* Avatar */}
          <div className="flex-shrink-0 pt-0.5">
            <div className={clsx(
              "w-8 h-8 rounded-lg flex items-center justify-center text-sm font-semibold",
              isUser
                ? "bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-sm"
                : "bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-sm"
            )}>
              {isUser ? <User size={16} /> : <Bot size={16} />}
            </div>
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1">
            <div className="mb-1.5 text-[13px] font-semibold text-fin-text">
              {isUser ? '你' : 'FinSight'}
            </div>
            <div className="text-[14.5px] leading-7 text-fin-text">
              {isUser ? (
                <p className="whitespace-pre-wrap m-0">{msg.content}</p>
              ) : (
                <div className="relative overflow-visible">
                  <AssistantContent msg={msg} onRetry={onRetry} onDelete={onDelete} actionsInline />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ── Main ChatList ──

export const ChatList: React.FC = () => {
  const {
    messages,
    isChatLoading,
    statusMessage,
    statusSince,
    executionProgress,
    currentStep,
    removeMessage,
    setStatus,
    setLoading,
    setTicker,
    addMessage,
    updateMessage,
    chatStyle,
  } = useStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [elapsed, setElapsed] = useState<string>('0.0');
  const isFlat = chatStyle === 'flat';
  const showExecutionBanner = isChatLoading
    || statusMessage === STOPPED_GENERATION_MESSAGE
    || currentStep === '已停止生成';

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
  }, [messages, isChatLoading, showExecutionBanner]);

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
      const response = await apiClient.sendMessage(query, undefined, {
        output_mode: 'chat',
        confirmation_mode: 'skip',
      });

      const chartInfo = await shouldGenerateChart(query, response.current_focus ?? null);
      const tickerToChart = chartInfo.tickers[0] || null;
      const evidencePool = (response as any).evidence_pool ?? response.data?.evidence_pool;

      let responseContent = typeof response.response === 'string'
        ? response.response
        : JSON.stringify(response.response, null, 2);
      const markerRegex = /\[CHART:([A-Z0-9.^=-]+):([a-z]+)\]/g;
      const existingTickers = new Set(
        Array.from(responseContent.matchAll(markerRegex)).map((match) => match[1])
      );
      const tickers = chartInfo.tickers.length ? chartInfo.tickers : extractTickers(query);
      const forceMulti = tickers.length > 1;
      if (chartInfo.chartType || forceMulti) {
        const targetTickers = tickers.slice(0, MAX_AUTO_CHART_TICKERS);
        const missingTickers = targetTickers.filter((ticker) => !existingTickers.has(ticker));
        if (missingTickers.length > 0) {
          const chartType = forceMulti ? 'line' : (chartInfo.chartType || 'line');
          missingTickers.forEach((ticker) => {
            responseContent += `\n\n[CHART:${ticker}:${chartType}]`;
          });
        }
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
        evidence_pool: evidencePool,
        report: response.report,
        isLoading: false,
      });

      const elapsedSeconds =
        (response.thinking_elapsed_seconds ?? (response.response_time_ms != null ? response.response_time_ms / 1000 : 0)).toFixed(1);
      setStatus(`Completed in ${elapsedSeconds}s`);

      if (response.current_focus || tickerToChart) {
        setTicker(response.current_focus || tickerToChart);
      }
    } catch {
      updateMessage(messageId, { content: originalMsg.content, isLoading: false });
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

  const renderMessages = () => {
    const items = messages.map((msg) =>
      isFlat ? (
        <FlatMessage
          key={msg.id}
          msg={msg}
          onRetry={() => handleRetry(msg.id)}
          onDelete={() => removeMessage(msg.id)}
        />
      ) : (
        <BubbleMessage
          key={msg.id}
          msg={msg}
          onRetry={() => handleRetry(msg.id)}
          onDelete={() => removeMessage(msg.id)}
        />
      )
    );

    if (isFlat) {
      return <>{items}</>;
    }
    return items;
  };

  return (
    <div
      id="chat-scroll-container"
      ref={containerRef}
      className={clsx("flex-1 overflow-y-auto", isFlat ? "p-0" : "p-4 md:p-6 lg:p-8 space-y-6")}
    >
      {renderMessages()}

      {showExecutionBanner && (
        <div className={clsx("flex w-full justify-start animate-fade-in", isFlat && "px-2 py-3")}>
          <div className={clsx(
            "rounded-xl border border-fin-border bg-fin-card px-4 py-3 shadow-sm min-w-[300px] max-w-[440px]",
            isFlat ? "max-w-3xl mx-auto w-full" : "ml-12"
          )}>
            <div className="flex items-center gap-2.5">
              <span className="relative flex h-2.5 w-2.5 shrink-0">
                <span className="absolute inline-flex h-full w-full rounded-full bg-fin-primary opacity-60 animate-ping" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-fin-primary" />
              </span>
              <span className="flex-1 truncate text-[13px] font-medium text-fin-text">
                {statusMessage === STOPPED_GENERATION_MESSAGE
                  ? '已停止生成（结果已保留）'
                  : statusMessage || '正在分析…'}
              </span>
              <span className="shrink-0 font-mono text-2xs tabular-nums text-fin-muted">{elapsed}s</span>
            </div>
            <div className="mt-2.5">
              <div className="h-1 overflow-hidden rounded-full bg-fin-border">
                <div
                  className="h-full rounded-full bg-fin-primary transition-all duration-500 ease-out"
                  style={{ width: `${Math.max(3, Math.min(100, executionProgress ?? 0))}%` }}
                />
              </div>
              <div className="mt-1.5 flex items-center justify-between gap-2">
                <span className="truncate text-2xs text-fin-text-secondary">{currentStep || '准备执行…'}</span>
                <span className="shrink-0 font-mono text-2xs tabular-nums text-fin-muted">{Math.round(executionProgress ?? 0)}%</span>
              </div>
            </div>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
};

// ── MessageWithChart ──

const MessageWithChart: React.FC<{ content: string }> = ({ content }) => {
  const [chartData, setChartData] = useState<Array<{ ticker: string; chartType: ChartType; summary: string }>>([]);

  const smartChartBlocks = useMemo(() => parseSmartChartBlocks(content), [content]);

  useEffect(() => {
    const matches = Array.from(content.matchAll(/\[CHART:([A-Z0-9.^=-]+):([a-z]+)\]/g));
    if (matches.length === 0) {
      setChartData([]);
      return;
    }
    const validChartTypes: ChartType[] = ['line', 'candlestick', 'pie', 'bar', 'tree', 'area', 'scatter', 'heatmap'];
    const seen = new Set<string>();
    const nextData: Array<{ ticker: string; chartType: ChartType; summary: string }> = [];
    matches.forEach((match) => {
      const ticker = match[1];
      const chartTypeStr = match[2];
      const chartType = (validChartTypes.includes(chartTypeStr as ChartType) ? chartTypeStr : 'line') as ChartType;
      const key = `${ticker}-${chartType}`;
      if (seen.has(key)) return;
      seen.add(key);
      nextData.push({ ticker, chartType, summary: '' });
    });
    setChartData(nextData);
  }, [content]);

  const handleChartDataReady = (ticker: string, summary: string) => {
    setChartData((prev) => prev.map((item) => (item.ticker === ticker ? { ...item, summary } : item)));
    sendChartDataToBackend(ticker, summary);
  };

  const sendChartDataToBackend = async (ticker: string, summary: string) => {
    try {
      await apiClient.addChartData(ticker, summary);
    } catch (err) {
      console.error('Chart data upload failed:', err);
    }
  };

  const textContent = stripSmartChartTags(
    content.replace(/\[CHART:[^\]]+\]/g, '')
  );

  return (
    <div className="prose prose-invert prose-sm max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <SourceLink href={href || ''} label={children} />
          ),
        }}
      >
        {normalizeMarkdown(textContent)}
      </ReactMarkdown>
      {chartData.map((chart) => (
        <InlineChart
          key={`${chart.ticker}-${chart.chartType}`}
          ticker={chart.ticker}
          chartType={chart.chartType}
          onDataReady={(_data, summary) => handleChartDataReady(chart.ticker, summary)}
        />
      ))}
      {smartChartBlocks.map((block, idx) => (
        <SmartChartRenderer key={`smart-${idx}-${block.type}-${block.title}`} block={block} />
      ))}
    </div>
  );
};

// ── SourceLink ──

const SourceLink: React.FC<{ href: string; label: React.ReactNode }> = ({ href, label }) => {
  const urlMeta = useMemo(() => {
    try {
      const url = new URL(href);
      return { domain: url.hostname.replace(/^www\./, '') };
    } catch {
      return { domain: '' };
    }
  }, [href]);

  const stringLabel = Array.isArray(label)
    ? label.map((node) => (typeof node === 'string' ? node : '')).join('')
    : typeof label === 'string'
      ? label
      : '';

  const displayText =
    stringLabel && stringLabel !== href
      ? stringLabel
      : urlMeta.domain || '来源链接';

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 px-2 py-1 rounded-full border border-fin-border/70 bg-fin-bg hover:border-fin-primary/80 hover:text-fin-primary transition text-fin-text no-underline"
      title={href}
    >
      {urlMeta.domain ? <Link2 size={14} /> : <ExternalLink size={14} />}
      <span className="truncate max-w-[160px]">{displayText}</span>
      {urlMeta.domain && (
        <span className="text-2xs text-fin-muted/70">({urlMeta.domain})</span>
      )}
    </a>
  );
};

// ── MessageActions ──

const MessageActions: React.FC<{
  messageId: string;
  content: string;
  thinking?: ThinkingStep[];
  report?: ReportIR;
  onRetry: () => void;
  onDelete: () => void;
  inline?: boolean;
}> = ({ content, thinking, report, onRetry, onDelete, inline }) => {
  const buildTraceMarkdown = () => {
    const lines: string[] = [];

    if (report) {
      lines.push(`# Report: ${report.title || report.ticker}`);
      lines.push(`Ticker: ${report.ticker}`);
      if (report.summary) {
        lines.push('');
        lines.push('## Summary');
        lines.push(report.summary);
      }
    }

    if (content) {
      lines.push('');
      lines.push('## Assistant Response');
      lines.push(content);
    }

    if (thinking && thinking.length > 0) {
      lines.push('');
      lines.push('## Reasoning Trace');
      thinking.forEach((step, idx) => {
        lines.push('');
        lines.push(`### ${idx + 1}. ${step.stage}`);
        if (step.message) lines.push(step.message);
        if (step.result) {
          lines.push('```json');
          lines.push(JSON.stringify(step.result, null, 2));
          lines.push('```');
        }
        if (step.timestamp) lines.push(`Time: ${new Date(step.timestamp).toLocaleString()}`);
      });
    }

    if (report?.citations?.length) {
      lines.push('');
      lines.push('## Sources');
      report.citations.forEach((citation) => {
        lines.push(`- [${citation.title || citation.source_id}](${citation.url}) (${citation.published_date || 'n/a'})`);
        if (citation.snippet) lines.push(`  - ${citation.snippet}`);
      });
    }

    return lines.filter((line) => line !== undefined).join('\n');
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
    } catch (e) {
      console.error('Copy failed', e);
    }
  };

  const handleExport = () => {
    const payload = buildTraceMarkdown() || content;
    const blob = new Blob([payload], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = report?.report_id ? `trace_${report.report_id}.md` : 'message.md';
    a.click();
    URL.revokeObjectURL(url);
  };

  const btnClass = "p-1.5 rounded-md hover:bg-fin-hover hover:text-fin-text transition-colors";

  return (
    <div className={clsx(
      "flex items-center gap-1 text-fin-muted pointer-events-auto",
      inline
        ? "mt-4 opacity-0 group-hover/msg:opacity-100 transition-opacity duration-200"
        : "absolute bottom-0 right-2 translate-y-full"
    )}>
      <button className={btnClass} title="复制" onClick={handleCopy}>
        <Copy size={14} />
      </button>
      <button className={btnClass} title="重试" onClick={onRetry}>
        <RefreshCcw size={14} />
      </button>
      <button className={btnClass} title="导出" onClick={handleExport}>
        <Download size={14} />
      </button>
      <button className={btnClass} title="删除" onClick={onDelete}>
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

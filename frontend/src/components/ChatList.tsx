import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User, Check, Copy, RefreshCcw, Trash2, Download, ExternalLink, Link2 } from 'lucide-react';
import { normalizeMarkdown } from '../utils/markdown';
import clsx from 'clsx';
import { InlineChart } from './InlineChart';
import { SmartChartRenderer, getRenderableMessageContent, parseSmartChartBlocks } from './SmartChart';
import { ThinkingProcess } from './thinking';
import { ReportView } from './report';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
import type { ChartType, ThinkingStep, ReportIR, EvidenceItem } from '../types/index';
import { useToast } from './ui/Toast';
import {
  MESSAGE_ACTION_LABELS,
  copyTextWithFeedback,
  messageActionContainerClass,
} from './chatMessageActions';
import { useChatStream } from '../hooks/useChatStream';

const STOPPED_GENERATION_MESSAGE = '已停止生成，保留已完成的结果。';

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
        <MessageWithChart content={msg.content} isStreaming={Boolean(msg.isLoading)} />
      ) : (
        <div className="py-4 flex items-center justify-start">
          <LoadingDots />
        </div>
      )
    ) : msg.report ? (
      <ReportView report={msg.report} />
    ) : (
      <MessageWithChart content={msg.content} isStreaming={Boolean(msg.isLoading)} />
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

const areMessagePropsEqual = (
  prev: { msg: MessagePayload },
  next: { msg: MessagePayload },
): boolean => prev.msg === next.msg;
// FE-03a：msg 在 store 中按不可变模式更新——内容变则引用变，历史消息引用稳定 → memo 命中。
// onRetry/onDelete 是内联箭头（引用不稳定）但行为只依赖 msg.id，故比较器有意忽略。

const BubbleMessageImpl: React.FC<{
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
        "p-3.5 rounded-lg text-sm leading-relaxed",
        msg.role === 'user'
          ? "bg-t-elevated border border-t-border/60 text-t-text"
          : "bg-t-card border border-t-border text-t-text relative overflow-visible"
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

const BubbleMessage = React.memo(BubbleMessageImpl, areMessagePropsEqual);

const FlatMessageImpl: React.FC<{
  msg: MessagePayload;
  onRetry: () => void;
  onDelete: () => void;
}> = ({ msg, onRetry, onDelete }) => {
  const isUser = msg.role === 'user';
  if (isUser) {
    // TERMINAL：用户消息 = 右对齐轻色块，无头像
    return (
      <div className="group/msg animate-slide-up py-3 px-4 md:px-6">
        <div className="max-w-[48rem] mx-auto flex justify-end">
          <div className="max-w-[72%] rounded-lg bg-t-elevated border border-t-border/60 px-3.5 py-2.5 text-sm leading-relaxed text-t-text">
            <p className="whitespace-pre-wrap m-0">{msg.content}</p>
          </div>
        </div>
      </div>
    );
  }
  // TERMINAL：AI 回答 = 无框文档流，左侧橙色竖线贯穿 + 等宽元信息行
  return (
    <div className="group/msg animate-slide-up py-3 px-4 md:px-6">
      <div className="max-w-[48rem] mx-auto">
        <div className="relative pl-4 border-l-2 border-t-accent/70">
          <div className="mb-1.5 flex items-center gap-2 text-2xs font-mono text-t-text3">
            <span className="font-semibold text-t-accent">FS▎</span>
            <span>FinSight</span>
          </div>
          <div className="text-[14.5px] leading-7 text-t-text relative overflow-visible">
            <AssistantContent msg={msg} onRetry={onRetry} onDelete={onDelete} actionsInline />
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
    sessionId,
    chatStyle,
  } = useStore();
  const chatStream = useChatStream(sessionId);
  const containerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [elapsed, setElapsed] = useState<string>('0.0');
  const isFlat = chatStyle === 'flat';
  const showExecutionBanner = isChatLoading
    || statusMessage === STOPPED_GENERATION_MESSAGE
    || currentStep === '已停止生成';

  // FE-02：滚动停靠检测——只有用户停靠在底部时才自动跟随，向上回看不再被拽回
  const PIN_THRESHOLD_PX = 80;
  const isPinnedRef = useRef(true);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    const pinned = distance < PIN_THRESHOLD_PX;
    isPinnedRef.current = pinned;
    setShowJumpToLatest((prev) => (prev === !pinned ? prev : !pinned));
  }, []);

  const jumpToLatest = useCallback(() => {
    const el = containerRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    isPinnedRef.current = true;
    setShowJumpToLatest(false);
  }, []);

  useEffect(() => {
    if (!isPinnedRef.current) return;
    const container = containerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight });
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

  const renderMessages = () => {
    const items = messages.map((msg) =>
      isFlat ? (
        <FlatMessage
          key={msg.id}
          msg={msg}
          onRetry={() => void chatStream.retry(msg.id)}
          onDelete={() => removeMessage(msg.id)}
        />
      ) : (
        <BubbleMessage
          key={msg.id}
          msg={msg}
          onRetry={() => void chatStream.retry(msg.id)}
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
      onScroll={handleScroll}
      className={clsx("flex-1 overflow-y-auto", isFlat ? "p-0" : "p-4 md:p-6 lg:p-8 space-y-6")}
    >
      {renderMessages()}

      {showJumpToLatest && (
        <button
          type="button"
          onClick={jumpToLatest}
          aria-label="回到最新消息"
          className="sticky bottom-4 left-1/2 -translate-x-1/2 z-10 rounded-full border border-fin-border bg-fin-card px-3 py-1.5 text-xs text-fin-text shadow-lg hover:border-fin-primary/60 transition-colors"
        >
          ↓ 回到最新
        </button>
      )}

      {showExecutionBanner && (
        <div role="status" aria-live="polite" className={clsx("flex w-full justify-start animate-fade-in", isFlat && "px-2 py-3")}>
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
              <div
                role="progressbar"
                aria-valuenow={Math.max(3, Math.min(100, executionProgress ?? 0))}
                aria-valuemin={0}
                aria-valuemax={100}
                className="h-1 overflow-hidden rounded-full bg-fin-border"
              >
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

const EMPTY_SMART_CHART_BLOCKS: ReturnType<typeof parseSmartChartBlocks> = [];

const MessageWithChart: React.FC<{ content: string; isStreaming?: boolean }> = ({ content, isStreaming }) => {
  const [chartData, setChartData] = useState<Array<{ ticker: string; chartType: ChartType; summary: string }>>([]);

  // FE-03b：流式中间态跳过全文图表正则解析（每 token 一次太贵），落定后一次解析
  const smartChartBlocks = useMemo(
    () => (isStreaming ? EMPTY_SMART_CHART_BLOCKS : parseSmartChartBlocks(content)),
    [content, isStreaming],
  );

  useEffect(() => {
    if (isStreaming) return; // CHART 标记由收尾阶段注入，流式期间无需扫描
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
  }, [content, isStreaming]);

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

  const textContent = getRenderableMessageContent(content, Boolean(isStreaming));

  return (
    <div className="prose prose-invert prose-sm max-w-none prose-terminal">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <SourceLink href={href || ''} label={children} />
          ),
          /* 移动端：长报告 markdown 表格加横向滚动容器，避免窄屏溢出撑破布局 */
          table: ({ children }) => (
            <div className="overflow-x-auto scrollbar-hide">
              <table>{children}</table>
            </div>
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
  const { toast } = useToast();
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

  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await copyTextWithFeedback(
      content,
      (text) => navigator.clipboard.writeText(text),
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      (error) => {
        console.error('Copy failed', error);
        toast({ type: 'error', title: '复制失败', message: '浏览器未允许访问剪贴板，请检查权限后重试。' });
      },
    );
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
    <div className={messageActionContainerClass(Boolean(inline))}>
      <button
        className={clsx(btnClass, copied && 'text-fin-success')}
        title={copied ? '已复制' : '复制'}
        aria-label={copied ? '已复制' : '复制回答'}
        onClick={handleCopy}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
      <button className={btnClass} title="重试" aria-label={MESSAGE_ACTION_LABELS.retry} onClick={onRetry}>
        <RefreshCcw size={14} />
      </button>
      <button className={btnClass} title="导出" aria-label={MESSAGE_ACTION_LABELS.export} onClick={handleExport}>
        <Download size={14} />
      </button>
      <button className={btnClass} title="删除" aria-label={MESSAGE_ACTION_LABELS.delete} onClick={onDelete}>
        <Trash2 size={14} />
      </button>
    </div>
  );
};

const LoadingDots: React.FC = () => {
  // TERMINAL：终端光标 + 真实阶段文案（取自 executionStore 的 statusMessage），拒绝三点弹跳
  const statusMessage = useStore((s) => s.statusMessage);
  return (
    <div className="flex items-center text-2xs font-mono text-t-text3">
      <span>{statusMessage || '正在分析'}</span>
      <span className="t-caret" />
    </div>
  );
};

const FlatMessage = React.memo(FlatMessageImpl, areMessagePropsEqual);

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Check, Copy, RefreshCcw, Trash2, Download, ExternalLink, Link2, ChartNoAxesCombined } from 'lucide-react';
import { normalizeMarkdown } from '../utils/markdown';
import clsx from 'clsx';
import { InlineChart } from './InlineChart';
import {
  SmartChartRenderer,
  getRenderableMessageContent,
  isPriceLikeInlineBlock,
  parseSmartChartBlocks,
  resolveRealPriceChartRequest,
} from './SmartChart';
import { ActivityRows, TurnActivity } from './chat/TurnActivity';
import { ResearchArtifactView } from './chat/ResearchArtifactView';
import { ActionConfirmationCard } from './chat/ActionConfirmationCard';
import { researchText } from '../store/researchStream';
import { ReasoningBlock } from './chat/ReasoningBlock';
import { buildMessageTimeline } from './chat/messageTimeline';
import styles from './chat/ChatDesign.module.css';
import { useCitationNavigation } from '../store/citationNavigation';
import { bindResearchCitations, citationId } from '../utils/researchCitations';
import { sourceDisplayName, sourceTitleDisplayName } from '../utils/sourceDisplayName';
import { EvidenceSources } from './source/EvidenceSources';
import { ReportView } from './report';
import { useStore } from '../store/useStore';
import type { ChartType, ThinkingStep, ReportIR, EvidenceItem, Message } from '../types/index';
import { useToast } from './ui/Toast';
import {
  MESSAGE_ACTION_LABELS,
  copyTextWithFeedback,
  messageActionContainerClass,
} from './chatMessageActions';
import { useChatStream } from '../hooks/useChatStream';
import { zh } from '../locales/zh';
import { EmptyState } from './ui/EmptyState';
import { extractTickers } from '../utils/ticker';
import { parseChartMarkers } from '../utils/chartIntent';
import { createTickerLinkPlugin, tickerFromDashboardHref } from '../utils/tickerMarkdown';
import { TickerLink } from './common/TickerLink';
import { ReportArchiveLink } from './common/ReportArchiveLink';

// ── Shared sub-components ──

const MessageEvidenceContext = React.createContext<{ sources: EvidenceItem[]; runId?: string }>({ sources: [] });

const DataOriginTag: React.FC<{ data_origin?: string; fallback_used?: boolean; as_of?: string | null; tried_sources?: string[] }> = ({
  data_origin, fallback_used, as_of, tried_sources,
}) => {
  if (!data_origin && !fallback_used) return null;
  const sourceLabel = sourceDisplayName(data_origin || 'LLM');
  return (
    <div className="mt-2 text-[11px] text-fin-muted flex items-center gap-2">
      <span className={`px-2 py-0.5 rounded-full border ${fallback_used ? 'border-amber-400/70 bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-200' : 'border-fin-border/60 bg-fin-bg/60'}`}>
        {zh.chat.source}: {sourceLabel} {fallback_used ? `(${zh.chat.fallback})` : ''}
      </span>
      {as_of && <span className="px-2 py-0.5 rounded-full border border-fin-border/60 bg-fin-bg/60">{zh.chat.asOf}: {as_of}</span>}
      {tried_sources && tried_sources.length > 0 && (
        <span className="text-2xs text-fin-muted/70">{zh.chat.triedSources}: {tried_sources.map(sourceDisplayName).join(' → ')}</span>
      )}
    </div>
  );
};

type MessagePayload = Message;

function MessageBlocks({ msg, onRetry }: { msg: MessagePayload; onRetry: () => void }) {
  const blocks = msg.blocks ?? [];
  const textMatches = researchText(blocks) === msg.content;
  const [expanded, setExpanded] = useState(Boolean(msg.isLoading));
  useEffect(() => { setExpanded(Boolean(msg.isLoading)); }, [msg.isLoading]);
  const timeline = buildMessageTimeline(blocks, msg.thinking ?? [], Boolean(msg.isLoading));
  const hasProgress = blocks.some((block) => block.kind === 'text' && block.content_phase === 'progress' && block.content.trim());
  const lastSeq = timeline.at(-1)?.seq;
  return <>
    <TurnActivity thinking={msg.thinking} isLoading={msg.isLoading} startedAt={msg.timestamp} error={msg.error} runStatus={msg.runStatus}
      summaryOnly expanded={expanded} onExpandedChange={setExpanded} hasProgress={hasProgress} />
    {timeline.map((item) => {
      if (item.kind === 'activity') return expanded ? <ActivityRows key={`activity:${item.rows[0].id}`} rows={item.rows} /> : null;
      const block = item.block;
      if (block.kind === 'text') {
        if (block.content_phase === 'progress') return expanded && block.content.trim()
          ? <div key={block.id} data-block-id={block.id} data-testid="research-progress" className={styles.progressText} aria-label="过程说明">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children }) => <SourceLink href={href || ''} label={children} /> }}>
              {normalizeMarkdown(bindResearchCitations(block.content, msg.evidence_pool ?? []))}
            </ReactMarkdown>
          </div> : null;
        return textMatches && !msg.report ? <div key={block.id} data-block-id={block.id}><MessageWithChart content={block.content} isStreaming={Boolean(msg.isLoading)} onRetry={onRetry} /></div> : null;
      }
      if (block.kind === 'artifact') return <ResearchArtifactView key={block.id} artifact={block.artifact} sources={msg.evidence_pool} />;
      if (block.kind === 'action') return <ActionConfirmationCard key={block.id} action={block.action} runId={msg.runId} />;
      return <ReasoningBlock key={block.id} block={block} live={Boolean(msg.isLoading && item.seq === lastSeq)} />;
    })}
    {msg.report ? <><ReportView report={msg.report} /><ReportArchiveLink reportId={msg.report.report_id} /></>
      : !textMatches && msg.content ? <MessageWithChart content={msg.content} isStreaming={Boolean(msg.isLoading)} onRetry={onRetry} /> : null}
    {msg.isLoading && !msg.content && !blocks.length && <div className="py-2"><LoadingDots /></div>}
  </>;
}

const AssistantContent: React.FC<{
  msg: MessagePayload;
  onRetry: () => void;
  onDelete: () => void;
  actionsInline?: boolean;
}> = ({ msg, onRetry, onDelete, actionsInline }) => (
  <MessageEvidenceContext.Provider value={{ sources: msg.evidence_pool ?? [], runId: msg.runId }}>
    <MessageBlocks msg={msg} onRetry={onRetry} />
    {msg.evidence_pool && msg.evidence_pool.length > 0 && (
      <EvidenceSources sources={msg.evidence_pool} />
    )}
    {msg.error && msg.content.trim() !== msg.error.trim() && <p role="alert" className="mt-3 border-l-2 border-fin-danger/50 pl-3 text-sm text-fin-danger">{msg.error}</p>}
    <DataOriginTag
      data_origin={msg.data_origin}
      fallback_used={msg.fallback_used}
      as_of={msg.as_of}
      tried_sources={msg.tried_sources}
    />
    {!msg.isLoading && msg.error && <button type="button"
      className="mt-3 min-h-10 rounded-lg border border-t-border px-3 text-sm text-t-text2 hover:border-t-accent/40"
      onClick={onRetry}>重新研究</button>}
    {!msg.isLoading && <MessageActions
      messageId={msg.id}
      content={msg.content}
      thinking={msg.thinking}
      report={msg.report}
      onRetry={onRetry}
      onDelete={onDelete}
      inline={actionsInline}
    />}
  </MessageEvidenceContext.Provider>
);

const areMessagePropsEqual = (prev: { msg: MessagePayload }, next: { msg: MessagePayload }): boolean => prev.msg === next.msg;

const FlatMessageImpl: React.FC<{
  msg: MessagePayload;
  onRetry: () => void;
  onDelete: () => void;
}> = ({ msg, onRetry, onDelete }) => {
  const isUser = msg.role === 'user';
  if (isUser) {
    // TERMINAL：用户消息 = 右对齐轻色块，无头像
    return (
      <div className={`chat-message group/msg ${styles.message}`}>
        <div className={styles.user}>
          <div className={styles.userBubble}>
            <p className="whitespace-pre-wrap m-0">{msg.content}</p>
          </div>
        </div>
      </div>
    );
  }
  // 助手回答采用无框阅读流，过程与产物保留在所属消息中。
  return (
    <div className={`chat-message group/msg ${styles.message} ${msg.blocks?.some((block) => block.kind === 'artifact') ? styles.messageWide : ''}`}>
      <div>
        <div className="relative">
          <div className={styles.answer}>
            <AssistantContent msg={msg} onRetry={onRetry} onDelete={onDelete} actionsInline />
          </div>
        </div>
      </div>
    </div>
  );
};

// ── Main ChatList ──

const FlatMessage = React.memo(FlatMessageImpl, areMessagePropsEqual);

export const ChatList: React.FC = () => {
  const messages = useStore((state) => state.messages);
  const visibleMessages = messages.some((message) => message.role === 'user') ? messages.filter((message) => message.id !== 'welcome') : messages;
  const sessionId = useStore((state) => state.sessionId);
  const removeMessage = useStore((state) => state.removeMessage);
  const chatStream = useChatStream(sessionId);
  const containerRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const handleScroll = useCallback(() => {
    const element = containerRef.current;
    if (!element) return;
    pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
    setShowJump(!pinned.current);
  }, []);
  useEffect(() => {
    if (pinned.current && containerRef.current) containerRef.current.scrollTo({ top: containerRef.current.scrollHeight });
  }, [messages]);
  useEffect(() => { pinned.current = true; setShowJump(false); }, [sessionId]);
  return <div id="chat-scroll-container" ref={containerRef} onScroll={handleScroll} className="relative min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-8 sm:px-6">
    {visibleMessages.map((msg) => <FlatMessage key={msg.id} msg={msg}
      onRetry={() => void chatStream.retry(msg.id)} onDelete={() => removeMessage(msg.id)} />)}
    {showJump && <button type="button" className="sticky bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-full border border-t-border bg-t-surface px-4 py-2 text-xs shadow-sm"
      onClick={() => { pinned.current = true; setShowJump(false); containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: 'smooth' }); }}
      aria-label={zh.chat.backToLatest}>↓ {zh.chat.backToLatest}</button>}
  </div>;
};

// ── MessageWithChart ──

const EMPTY_SMART_CHART_BLOCKS: ReturnType<typeof parseSmartChartBlocks> = [];

const MessageWithChart: React.FC<{ content: string; isStreaming?: boolean; onRetry: () => void }> = ({ content, isStreaming, onRetry }) => {
  const evidence = React.useContext(MessageEvidenceContext);
  const [chartData, setChartData] = useState<Array<{
    ticker: string;
    chartType: ChartType;
    valueMode: 'close' | 'return';
    period: string;
  }>>([]);

  // FE-03b：流式中间态跳过全文图表正则解析（每 token 一次太贵），落定后一次解析
  const smartChartBlocks = useMemo(
    () => (isStreaming ? EMPTY_SMART_CHART_BLOCKS : parseSmartChartBlocks(content)),
    [content, isStreaming],
  );
  const tickerCandidates = useMemo(() => extractTickers(content), [content]);
  const tickerLinkPlugin = useMemo(
    () => createTickerLinkPlugin(tickerCandidates),
    [tickerCandidates],
  );

  useEffect(() => {
    if (isStreaming) return; // CHART 标记由收尾阶段注入，流式期间无需扫描
    const matches = parseChartMarkers(content);
    if (matches.length === 0) {
      setChartData([]);
      return;
    }
    const validChartTypes: ChartType[] = ['line', 'candlestick', 'pie', 'bar', 'tree', 'area', 'scatter', 'heatmap'];
    const seen = new Set<string>();
    const nextData: Array<{
      ticker: string;
      chartType: ChartType;
      valueMode: 'close' | 'return';
      period: string;
    }> = [];
    matches.forEach((match) => {
      const ticker = match.ticker;
      const chartTypeStr = match.chartType;
      const chartType = (validChartTypes.includes(chartTypeStr as ChartType) ? chartTypeStr : 'line') as ChartType;
      const key = `${ticker}-${chartType}-${match.valueMode}-${match.period}`;
      if (seen.has(key)) return;
      seen.add(key);
      nextData.push({
        ticker,
        chartType,
        valueMode: match.valueMode,
        period: match.period,
      });
    });
    setChartData(nextData);
  }, [content, isStreaming]);

  const textContent = bindResearchCitations(getRenderableMessageContent(content, Boolean(isStreaming)), evidence.sources);

  return (
    <div className="prose prose-invert prose-sm max-w-none prose-terminal">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, tickerLinkPlugin]}
        components={{
          a: ({ href, children }) => {
            const ticker = tickerFromDashboardHref(href);
            return ticker
              ? <TickerLink ticker={ticker}>{children}</TickerLink>
              : <SourceLink href={href || ''} label={children} />;
          },
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
          key={`${chart.ticker}-${chart.chartType}-${chart.valueMode}-${chart.period}`}
          ticker={chart.ticker}
          chartType={chart.chartType}
          valueMode={chart.valueMode}
          period={chart.period}
        />
      ))}
      {smartChartBlocks.map((block, idx) => {
        const key = `smart-${idx}-${block.type}-${block.title}`;
        const realPriceRequest = resolveRealPriceChartRequest(block, tickerCandidates);
        if (realPriceRequest) {
          return (
            <InlineChart
              key={key}
              ticker={realPriceRequest.ticker}
              chartType={realPriceRequest.chartType}
              valueMode={realPriceRequest.valueMode}
            />
          );
        }
        if (isPriceLikeInlineBlock(block)) {
          return (
            <div key={key} className="my-4 rounded-lg border border-fin-border bg-fin-panel px-4">
              <EmptyState
                icon={ChartNoAxesCombined}
                message="行情图暂不可用：未识别到可查询的标的。"
                action={{ label: '重新生成', onClick: onRetry }}
              />
            </div>
          );
        }
        return <SmartChartRenderer key={key} block={block} />;
      })}
    </div>
  );
};

// ── SourceLink ──

const SourceLink: React.FC<{ href: string; label: React.ReactNode }> = ({ href, label }) => {
  const evidence = React.useContext(MessageEvidenceContext);
  const sourceIndex = evidence.sources.findIndex((source, index) => source.url === href
    || href === `#research-source-${encodeURIComponent(citationId(source, index))}`);
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
      : urlMeta.domain || zh.chat.sourceLink;

  const isCitation = href.startsWith('#research-source-') || /^\[?(?:\d+|S[a-f0-9]+)\]?$/i.test(stringLabel.trim());
  if (sourceIndex >= 0 && isCitation) return <a href={href} className={styles.citation}
    title={sourceTitleDisplayName(evidence.sources[sourceIndex].title, evidence.sources[sourceIndex].source || displayText)} aria-label={`查看引用 ${sourceIndex + 1}`}
    onClick={(event) => {
      event.preventDefault();
      useStore.getState().setShowRightPanel(true);
      useCitationNavigation.getState().select({ sessionId: useStore.getState().sessionId, runId: evidence.runId,
        sourceId: citationId(evidence.sources[sourceIndex], sourceIndex) });
    }}>{sourceIndex + 1}</a>;

  if (sourceIndex >= 0) return <a href={href} target="_blank" rel="noopener noreferrer" className={styles.articleLink}>{label || displayText}</a>;

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
        toast({ type: 'error', title: zh.chat.copyFailedTitle, message: zh.chat.copyFailedMessage });
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
        title={copied ? zh.chat.copied : zh.chat.copy}
        aria-label={copied ? zh.chat.copied : zh.chat.copyAnswer}
        onClick={handleCopy}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
      <button className={btnClass} title={zh.chat.retry} aria-label={MESSAGE_ACTION_LABELS.retry} onClick={onRetry}>
        <RefreshCcw size={14} />
      </button>
      <button className={btnClass} title={zh.chat.export} aria-label={MESSAGE_ACTION_LABELS.export} onClick={handleExport}>
        <Download size={14} />
      </button>
      <button className={btnClass} title={zh.chat.delete} aria-label={MESSAGE_ACTION_LABELS.delete} onClick={onDelete}>
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
      <span>{statusMessage || zh.chat.analyzingShort}</span>
      <span className="t-caret" />
    </div>
  );
};

import { Eraser, Moon, Plus, Sun, Bell, ChevronUp, Loader2, MessageSquare, Trash2, MessageSquareText, AlignLeft } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import { AgentLogPanel } from '../agent-log';
import { ExecutionPanel } from '../execution/ExecutionPanel';
import { ChatInput } from '../ChatInput';
import { ChatList } from '../ChatList';
import { ContextPanelShell } from './ContextPanelShell';
import type { MarketQuote } from '../../hooks/useMarketQuotes';
import { apiClient } from '../../api/client';
import { useExecutionStore } from '../../store/executionStore';
import { useStore } from '../../store/useStore';
import type { ConversationSummary } from '../../store/useStore';

type ChatWorkspaceProps = {
  isMobile: boolean;
  theme: 'dark' | 'light';
  onToggleTheme: () => void;
  onDashboardRequest: (symbol: string) => void;
  contextPanel: {
    panelWidth: number;
    isExpanded: boolean;
    onExpand: () => void;
    onCollapse: () => void;
    onResizeStart: (event: MouseEvent) => void;
    onSubscribeClick: () => void;
    autoSwitchExecution?: boolean;
    onNavigateToChat?: () => void;
  };
  marketQuotes: MarketQuote[];
  initialReportId?: string | null;
};

const formatChangePct = (value?: number) => {
  if (value === undefined || Number.isNaN(value)) return null;
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

const formatConversationTime = (timestamp: number) => {
  const value = Number(timestamp || 0);
  if (!Number.isFinite(value) || value <= 0) return '';
  const diff = Date.now() - value;
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return '刚刚';
  if (diff < hour) return `${Math.max(1, Math.floor(diff / minute))} 分钟前`;
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`;
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`;
  return new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
};

const confirmDeleteConversation = (conversation: ConversationSummary) => {
  if (typeof window === 'undefined') return true;
  return window.confirm(`删除会话「${conversation.title || '新对话'}」？`);
};

export function ChatWorkspace({
  isMobile,
  theme,
  onToggleTheme,
  onDashboardRequest,
  contextPanel,
  marketQuotes,
  initialReportId,
}: ChatWorkspaceProps) {
  const traceViewMode = useStore((state) => state.traceViewMode);
  const chatStyle = useStore((state) => state.chatStyle);
  const setChatStyle = useStore((state) => state.setChatStyle);
  const sessionId = useStore((state) => state.sessionId);
  const conversationSummaries = useStore((state) => state.conversationSummaries);
  const selectConversation = useStore((state) => state.selectConversation);
  const deleteConversation = useStore((state) => state.deleteConversation);
  const startNewChat = useStore((state) => state.startNewChat);
  const clearConversationContext = useStore((state) => state.clearConversationContext);
  const latestRunId = useExecutionStore((state) => (
    state.activeRuns[state.activeRuns.length - 1]?.runId
      ?? state.recentRuns[0]?.runId
      ?? null
  ));
  const latestRunStatus = useExecutionStore((state) => {
    const run = state.activeRuns[state.activeRuns.length - 1]
      ?? state.recentRuns[0]
      ?? null;
    return run?.status ?? null;
  });

  const [execCollapsed, setExecCollapsed] = useState(true);

  // 执行中自动展开，完成后自动折叠
  useEffect(() => {
    if (latestRunStatus === 'running' || latestRunStatus === 'interrupted') {
      setExecCollapsed(false);
    } else if (latestRunStatus === 'done' || latestRunStatus === 'error') {
      setExecCollapsed(true);
    }
  }, [latestRunStatus]);

  // --- P0-2: report_id replay ---
  const replayLoadedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!initialReportId) return;
    // Prevent double-loading if the same reportId is already loaded
    if (replayLoadedRef.current === initialReportId) return;
    replayLoadedRef.current = initialReportId;

    const sessionId = useStore.getState().sessionId;
    if (!sessionId) return;

    apiClient
      .getReportReplay({ sessionId, reportId: initialReportId })
      .then((data) => {
        if (data.success && data.report) {
          const { addMessage } = useStore.getState();
          addMessage({
            id: `replay-${initialReportId}-${Date.now()}`,
            role: 'assistant',
            content: data.report.title || 'Report replay',
            timestamp: Date.now(),
            report: data.report,
          });
        }
      })
      .catch((err) => {
        console.error('[ChatWorkspace] Report replay failed:', err);
      });
  }, [initialReportId]);

  return (
    <div className="flex-1 min-w-0 flex flex-col h-full overflow-hidden relative">
      <header className="h-[60px] bg-fin-card border-b border-fin-border flex items-center justify-between px-6 shrink-0 max-lg:px-3">
        <div className="flex gap-4 text-xs text-fin-text font-medium overflow-x-auto scrollbar-hide">
          {marketQuotes.map((quote) => (
            <span key={quote.label} className="flex items-center gap-1 whitespace-nowrap">
              {quote.flag} {quote.label}:{' '}
              {quote.loading ? (
                <span className="text-fin-muted">...</span>
              ) : quote.changePct !== undefined ? (
                <span className={quote.changePct >= 0 ? 'text-fin-success' : 'text-fin-danger'}>
                  {formatChangePct(quote.changePct)}
                </span>
              ) : quote.price !== undefined ? (
                <span className="text-fin-warning">${quote.price.toLocaleString()}</span>
              ) : (
                <span className="text-fin-muted">--</span>
              )}
            </span>
          ))}
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <button
            type="button"
            onClick={startNewChat}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-xs font-medium text-fin-text"
            title="新建对话"
            aria-label="新建对话"
          >
            <Plus size={14} />
            <span className="hidden sm:inline">新对话</span>
          </button>
          <button
            type="button"
            onClick={clearConversationContext}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-xs font-medium text-fin-text"
            title="清空上下文"
            aria-label="清空上下文"
          >
            <Eraser size={14} />
            <span className="hidden sm:inline">清空</span>
          </button>
          <button
            type="button"
            onClick={() => setChatStyle(chatStyle === 'bubble' ? 'flat' : 'bubble')}
            className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary"
            title={chatStyle === 'bubble' ? '切换平铺布局' : '切换气泡布局'}
            aria-label="切换聊天布局"
          >
            {chatStyle === 'bubble' ? <AlignLeft size={16} /> : <MessageSquareText size={16} />}
          </button>
          <button
            type="button"
            onClick={onToggleTheme}
            className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary"
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button
            type="button"
            onClick={contextPanel.onExpand}
            className="relative p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary"
            title="告警与订阅"
            aria-label="告警与订阅"
          >
            <Bell size={16} />
          </button>
          <button
            type="button"
            className="px-3 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-xs font-medium text-fin-text"
          >
            导出 PDF
          </button>
        </div>
      </header>

      <div className="flex-1 min-h-0 flex overflow-hidden p-5 gap-4 max-lg:flex-col max-lg:p-3">
        <aside
          data-testid="conversation-rail"
          className="w-64 shrink-0 bg-fin-card border border-fin-border rounded-2xl overflow-hidden flex flex-col min-h-0 max-lg:w-full max-lg:max-h-44"
        >
          <div className="h-11 px-3 border-b border-fin-border flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2 text-xs font-semibold text-fin-text">
              <MessageSquare size={14} className="text-fin-muted" />
              会话
            </div>
            <button
              type="button"
              onClick={startNewChat}
              className="p-1.5 rounded-md text-fin-muted hover:text-fin-text hover:bg-fin-hover transition-colors"
              title="新建对话"
              aria-label="新建对话"
            >
              <Plus size={14} />
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1" role="list" aria-label="会话列表">
            {conversationSummaries.map((conversation) => {
              const active = conversation.sessionId === sessionId;
              return (
                <div
                  key={conversation.sessionId}
                  role="listitem"
                  data-testid="conversation-item"
                  data-session-id={conversation.sessionId}
                  data-active={active ? 'true' : 'false'}
                  className={`group w-full min-h-[58px] rounded-lg border transition-colors flex items-stretch ${
                    active
                      ? 'bg-fin-primary/10 border-fin-primary/30 text-fin-text'
                      : 'border-transparent text-fin-text-secondary hover:bg-fin-hover hover:text-fin-text'
                  }`}
                  title={conversation.title}
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (!active) selectConversation(conversation.sessionId);
                    }}
                    className="min-w-0 flex-1 px-2.5 py-2 text-left"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-xs font-medium">{conversation.title || '新对话'}</div>
                      <div className="mt-1 flex items-center gap-2 text-2xs text-fin-muted">
                        <span>{formatConversationTime(conversation.updatedAt)}</span>
                        <span>{conversation.messageCount} 条</span>
                      </div>
                      {conversation.lastMessagePreview && (
                        <div className="mt-1 truncate text-2xs text-fin-muted">
                          {conversation.lastMessagePreview}
                        </div>
                      )}
                    </div>
                  </button>
                  <button
                    type="button"
                    className="shrink-0 self-start mt-1.5 mr-1.5 opacity-0 group-hover:opacity-100 focus:opacity-100 p-1 rounded-md text-fin-muted hover:text-red-300 hover:bg-red-500/10 transition"
                    title="删除会话"
                    aria-label="删除会话"
                    data-testid="conversation-delete"
                    onClick={(event) => {
                      event.stopPropagation();
                      if (confirmDeleteConversation(conversation)) {
                        deleteConversation(conversation.sessionId);
                      }
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              );
            })}
          </div>
        </aside>
        <div className="flex-1 min-w-0 min-h-0 flex flex-col gap-3 overflow-hidden">
          <div className="flex-1 bg-fin-card border border-fin-border rounded-2xl flex flex-col overflow-hidden shadow-sm min-h-0">
            <ChatList />
            <ChatInput onDashboardRequest={onDashboardRequest} />
          </div>
          <div className="shrink-0">
            {traceViewMode === 'dev' ? (
              <AgentLogPanel />
            ) : latestRunId ? (
              execCollapsed ? (
                <button
                  type="button"
                  onClick={() => setExecCollapsed(false)}
                  className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl border border-fin-border bg-fin-card text-xs text-fin-muted hover:bg-fin-hover transition-colors"
                >
                  <span className="flex items-center gap-1.5">
                    {latestRunStatus === 'running' && <Loader2 size={12} className="animate-spin text-blue-300" />}
                    执行追踪（已折叠）
                  </span>
                  <ChevronUp size={14} />
                </button>
              ) : (
                <ExecutionPanel
                  runId={latestRunId}
                  mode={traceViewMode === 'expert' ? 'expert' : 'user'}
                  collapsible
                  onCollapse={() => setExecCollapsed(true)}
                />
              )
            ) : null}
          </div>
        </div>

        <ContextPanelShell
          isMobile={isMobile}
          panelWidth={contextPanel.panelWidth}
          isExpanded={contextPanel.isExpanded}
          onExpand={contextPanel.onExpand}
          onCollapse={contextPanel.onCollapse}
          onResizeStart={contextPanel.onResizeStart}
          onSubscribeClick={contextPanel.onSubscribeClick}
          autoSwitchExecution={contextPanel.autoSwitchExecution}
          onNavigateToChat={contextPanel.onNavigateToChat}
          showMiniChat={false}
        />
      </div>
    </div>
  );
}

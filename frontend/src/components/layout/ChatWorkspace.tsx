import { Eraser, Moon, Sun, PanelRightOpen } from 'lucide-react';
import { useEffect, useRef } from 'react';
import type { MouseEvent } from 'react';
import { AgentLogPanel } from '../agent-log';
import { ChatInput } from '../ChatInput';
import { ChatList } from '../ChatList';
import type { MarketQuote } from '../../hooks/useMarketQuotes';
import { useDeveloperMode } from '../../hooks/useDeveloperMode';
import { apiClient } from '../../api/client';
import { useStore } from '../../store/useStore';
import { observedMessageTickers } from "../RightPanel.utils";

type ChatWorkspaceProps = {
  theme: 'dark' | 'light';
  onToggleTheme: () => void;
  onDashboardRequest: (symbol: string) => void;
  contextPanel: {
    panelWidth: number;
    isExpanded: boolean;
    onExpand: () => void;
    onCollapse: () => void;
    onResizeStart: (event: MouseEvent) => void;
  };
  marketQuotes: MarketQuote[];
  initialReportId?: string | null;
  initialDraft?: string | null;
};

export function ChatWorkspace({
  theme,
  onToggleTheme,
  onDashboardRequest,
  contextPanel,
  initialReportId,
  initialDraft,
}: ChatWorkspaceProps) {
  const [developerMode] = useDeveloperMode();
  const sessionId = useStore((state) => state.sessionId);
  const conversationSummaries = useStore((state) => state.conversationSummaries);
  const hasUserMessages = useStore((state) => state.messages.some((message) => message.role === 'user'));
  const turnCount = useStore((state) => state.messages.filter((message) => message.role === 'user').length);
  const updatedAt = useStore((state) => state.messages.at(-1)?.timestamp);
  const latestResearch = useStore((state) => [...state.messages].reverse().find((message) => message.role === 'assistant' && message.runId));
  const observedTickers = observedMessageTickers(latestResearch);
  const sourceCount = latestResearch?.evidence_pool?.length ?? 0;
  const clearConversationContext = useStore((state) => state.clearConversationContext);
  const setDraft = useStore((state) => state.setDraft);

  const loadedDraftRef = useRef<string | null>(null);

  useEffect(() => {
    const nextDraft = initialDraft?.trim();
    if (!nextDraft) return;
    // 登录态/匿名态初始化可能在路由挂载后切换 session，并清空当前 draft。
    // 按 session 记录已加载键，确保深链草稿在最终会话中仍能恢复。
    const loadedDraftKey = `${sessionId}\u0000${nextDraft}`;
    if (loadedDraftRef.current === loadedDraftKey) return;
    loadedDraftRef.current = loadedDraftKey;
    setDraft(nextDraft);
  }, [initialDraft, sessionId, setDraft]);

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
        if (data.report) {
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
        <div className="min-w-0 flex-1 pr-3">
          <h1 className="truncate text-[14.5px] font-semibold text-t-text">{hasUserMessages ? conversationSummaries.find((item) => item.sessionId === sessionId)?.title || '新对话' : '新对话'}</h1>
          <p className="mt-0.5 text-xs text-t-text3 max-sm:hidden">{turnCount && updatedAt
            ? `${turnCount} 轮 · 更新于 ${new Date(updatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })}`
            : '输入问题，查看依据'}</p>
          {latestResearch && <p className="mt-0.5 text-xs text-t-text3 max-sm:hidden">{observedTickers.join('、') || '当前对话'} · {sourceCount} 个来源</p>}
        </div>

        <div className="flex items-center gap-2 shrink-0 max-lg:justify-end max-lg:overflow-x-auto scrollbar-hide">
          <button
            type="button"
            onClick={clearConversationContext}
            className="design-ghost [@media(pointer:coarse)]:min-h-11"
            title="清空上下文"
            aria-label="清空上下文"
          >
            <Eraser size={14} />
            <span className="hidden sm:inline">清空</span>
          </button>
          <button
            type="button"
            onClick={onToggleTheme}
            className="design-ghost [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:min-w-11"
            title={theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
            aria-label={theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button
            type="button"
            data-testid={!contextPanel.isExpanded ? 'context-panel-expand' : undefined}
            onClick={contextPanel.isExpanded ? contextPanel.onCollapse : contextPanel.onExpand}
            className="design-ghost relative [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:min-w-11"
            title={contextPanel.isExpanded ? '收起标的面板' : '展开标的与研究详情'}
            aria-label={contextPanel.isExpanded ? '收起标的面板' : '展开标的与研究详情'}
          >
            <PanelRightOpen size={16} />
          </button>
        </div>
      </header>

      <div className="flex-1 min-h-0 flex overflow-hidden">

        <div className="flex-1 min-w-0 min-h-0 flex flex-col gap-3 overflow-hidden">
          <div className="flex-1 bg-t-bg flex flex-col overflow-hidden min-h-0">
            <ChatList />
            <ChatInput onDashboardRequest={onDashboardRequest} />
          </div>
          {developerMode && <div className="shrink-0"><AgentLogPanel /></div>}
        </div>

      </div>
    </div>
  );
}

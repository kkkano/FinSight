import type { Message, AgentLogEntry, AgentStatus, AgentLogSource, RawSSEEvent, TraceViewMode } from '../types';
import type { PendingChatHandoffContext } from '../types/chatHandoff';

export type Theme = 'dark' | 'light';

export type ColorConvention = 'intl' | 'cn';

export type LayoutMode = 'centered' | 'full';

export type ChatStyle = 'bubble' | 'flat';

export type EntryMode = 'pending' | 'anonymous' | 'authenticated';

export interface AuthIdentity {
  userId: string;
  email: string | null;
}

export interface ConversationSummary {
  tickers?: string[];
  runStatus?: string;
  answerStatus?: string;
  sessionId: string;
  title: string;
  lastMessagePreview: string;
  messageCount: number;
  createdAt: number;
  updatedAt: number;
}

export interface ChatSessionStatus {
  statusMessage: string | null;
  statusSince: number | null;
  executionProgress: number | null;
  currentStep: string | null;
}

export interface MessageRecoveryGuard {
  ownerId: string | null;
  runId: string;
  userMessageId: string;
  controller: AbortController;
  timestamp: number;
}

export interface AppState {
  messages: Message[];
  addMessage: (message: Message) => void;
  addMessageToSession: (sessionId: string, message: Message) => void;
  updateMessage: (id: string, patch: Partial<Message>) => void;
  updateMessageInSession: (sessionId: string, id: string, patch: Partial<Message>, options?: {
    syncBackend?: boolean; recovery?: MessageRecoveryGuard;
  }) => void;
  flushConversationSync: (sessionId: string) => Promise<boolean>;
  updateLastMessage: (content: string) => void;
  removeMessage: (id: string) => void;
  setLoading: (loading: boolean) => void;
  setSessionLoading: (sessionId: string, loading: boolean) => void;
  isChatLoading: boolean;
  chatLoadingBySession: Record<string, boolean>;
  chatStatusBySession: Record<string, ChatSessionStatus>;
  statusMessage: string | null;
  statusSince: number | null;
  executionProgress: number | null;
  currentStep: string | null;
  setStatus: (message: string | null) => void;
  setExecutionState: (step: string | null, progress?: number | null) => void;
  resetExecutionState: () => void;
  abortController: AbortController | null;
  abortControllersBySession: Record<string, AbortController | null>;
  setAbortController: (controller: AbortController | null) => void;
  setSessionAbortController: (sessionId: string, controller: AbortController | null) => void;
  cancelChatStream: () => void;
  clearConversationContext: () => void;
  startNewChat: () => void;
  conversationSummaries: ConversationSummary[];
  selectConversation: (sessionId: string) => void;
  deleteConversation: (sessionId: string) => void;
  currentTicker: string | null;
  setTicker: (ticker: string | null) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  colorConvention: ColorConvention;
  setColorConvention: (colorConvention: ColorConvention) => void;
  layoutMode: LayoutMode;
  setLayoutMode: (mode: LayoutMode) => void;
  watchlistAutoConfirm: boolean;
  setWatchlistAutoConfirm: (enabled: boolean) => void;
  showProviderReasoning: boolean;
  setShowProviderReasoning: (enabled: boolean) => void;
  chatStyle: ChatStyle;
  setChatStyle: (style: ChatStyle) => void;
  setDraft: (text: string) => void;
  draft: string;
  draftBySession: Record<string, string>;
  pendingChatHandoffContextBySession: Record<string, PendingChatHandoffContext | undefined>;
  setPendingChatHandoffContext: (sessionId: string, value: PendingChatHandoffContext) => void;
  takePendingChatHandoffContext: (sessionId: string) => PendingChatHandoffContext | undefined;
  entryMode: EntryMode;
  setEntryMode: (mode: EntryMode) => void;
  sessionId: string;
  setSessionId: (sessionId: string) => void;
  authIdentity: AuthIdentity | null;
  setAuthIdentity: (identity: AuthIdentity | null) => void;
  // Agent Logs - 实时日志面板
  agentLogs: AgentLogEntry[];
  agentStatuses: Record<AgentLogSource, AgentStatus>;
  addAgentLog: (log: AgentLogEntry) => void;
  updateAgentStatus: (source: AgentLogSource, status: Partial<AgentStatus>) => void;
  clearAgentLogs: () => void;
  setAgentLogsPanelOpen: (open: boolean) => void;
  isAgentLogsPanelOpen: boolean;
  // Raw SSE Events - 开发者控制台
  rawEvents: RawSSEEvent[];
  addRawEvent: (event: RawSSEEvent) => void;
  clearRawEvents: () => void;
  isConsoleOpen: boolean;
  setConsoleOpen: (open: boolean) => void;
  traceRawEnabled: boolean;
  setTraceRawEnabled: (enabled: boolean) => void;
  traceViewMode: TraceViewMode;
  setTraceViewMode: (mode: TraceViewMode) => void;
  traceRawShowRawJson: boolean;
  setTraceRawShowRawJson: (show: boolean) => void;
  requestMetrics: {
    llmTotalCalls: number;
    toolTotalCalls: number;
    updatedAt: string | null;
  };
  setRequestMetrics: (metrics: Partial<{ llmTotalCalls: number; toolTotalCalls: number; updatedAt: string | null }>) => void;
  // 右侧面板全局可见性 - 供快捷键切换
  showRightPanel: boolean;
  setShowRightPanel: (show: boolean) => void;
  toggleRightPanel: () => void;
}

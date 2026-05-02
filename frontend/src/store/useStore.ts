import { create } from 'zustand';
import type { Message, AgentLogEntry, AgentStatus, AgentLogSource, RawSSEEvent, TraceViewMode } from '../types';

type Theme = 'dark' | 'light';
type LayoutMode = 'centered' | 'full';
type PortfolioPositions = Record<string, number>;
export type EntryMode = 'pending' | 'anonymous' | 'authenticated';
export interface AuthIdentity {
  userId: string;
  email: string | null;
}

export interface ConversationSummary {
  sessionId: string;
  title: string;
  lastMessagePreview: string;
  messageCount: number;
  createdAt: number;
  updatedAt: number;
}

const DEFAULT_USER_ID = 'default_user';
const SESSION_PART_PATTERN = /[^A-Za-z0-9._-]/g;
const normalizeSessionPart = (value: string, fallback: string): string => {
  const normalized = String(value || '').trim().replace(SESSION_PART_PATTERN, '-').slice(0, 64);
  return normalized || fallback;
};

const getInitialLayout = (): LayoutMode => {
  if (typeof window === 'undefined') return 'centered';
  const stored = window.localStorage.getItem('finsight-layout');
  return stored === 'full' || stored === 'centered' ? (stored as LayoutMode) : 'centered';
};

const getInitialTheme = (): Theme => {
  if (typeof window === 'undefined') return 'dark';
  const stored = window.localStorage.getItem('finsight-theme');
  if (stored === 'light' || stored === 'dark') return stored;
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  return prefersDark ? 'dark' : 'light';
};

const getInitialSubscriptionEmail = (): string => {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem('finsight-subscription-email') || '';
};

const getInitialEntryMode = (): EntryMode => {
  if (typeof window === 'undefined') return 'pending';
  const raw = window.localStorage.getItem('finsight-entry-mode');
  return raw === 'pending' || raw === 'anonymous' || raw === 'authenticated'
    ? (raw as EntryMode)
    : 'pending';
};

export const buildAnonymousSessionId = (): string => {
  const randomPart =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return `public:anonymous:${randomPart}`;
};

export const buildUserSessionId = (userId: string, thread: string = 'default'): string => {
  const normalizedUser = normalizeSessionPart(userId, 'user');
  const normalizedThread = normalizeSessionPart(thread, 'default');
  return `public:${normalizedUser}:${normalizedThread}`;
};

export const deriveUserIdFromSessionId = (sessionId: string | null | undefined): string => {
  const raw = (sessionId || '').trim();
  if (!raw) return DEFAULT_USER_ID;

  const parts = raw.split(':');
  if (parts.length >= 2) {
    const candidate = parts[1]?.trim();
    if (candidate) return candidate;
  }

  if (parts.length === 1) {
    return DEFAULT_USER_ID;
  }

  return DEFAULT_USER_ID;
};

const getInitialSessionId = (): string | null => {
  if (typeof window === 'undefined') return null;
  const raw = window.localStorage.getItem('finsight-session-id');
  if (!raw) {
    const generated = buildAnonymousSessionId();
    window.localStorage.setItem('finsight-session-id', generated);
    return generated;
  }
  const trimmed = raw.trim();
  if (!trimmed) {
    const generated = buildAnonymousSessionId();
    window.localStorage.setItem('finsight-session-id', generated);
    return generated;
  }
  return trimmed;
};

const getInitialTraceRawEnabled = (): boolean => {
  if (typeof window === 'undefined') return true;
  const raw = window.localStorage.getItem('finsight-trace-raw-enabled');
  if (raw === null) return true;
  return raw === 'true';
};
const getInitialTraceRawShowRawJson = (): boolean => {
  if (typeof window === 'undefined') return true;
  const raw = window.localStorage.getItem('finsight-trace-raw-show-json');
  if (raw === null) return true;
  return raw === 'true';
};
const getInitialTraceViewMode = (): TraceViewMode => {
  if (typeof window === 'undefined') return 'expert';
  const raw = window.localStorage.getItem('finsight-trace-view-mode');
  return raw === 'user' || raw === 'expert' || raw === 'dev' ? (raw as TraceViewMode) : 'expert';
};

const getInitialPortfolioPositions = (): PortfolioPositions => {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem('finsight-portfolio-positions');
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    return Object.entries(parsed).reduce<PortfolioPositions>((acc, [ticker, shares]) => {
      const normalized = ticker.trim().toUpperCase();
      const value = Number(shares);
      if (normalized && Number.isFinite(value) && value > 0) {
        acc[normalized] = value;
      }
      return acc;
    }, {});
  } catch {
    return {};
  }
};

const persistPortfolioPositions = (positions: PortfolioPositions) => {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem('finsight-portfolio-positions', JSON.stringify(positions));
};

const applyThemeClass = (theme: Theme) => {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('light', theme === 'light');
  root.classList.toggle('dark', theme === 'dark');
};

const initialTheme = getInitialTheme();
const initialLayout = getInitialLayout();
const initialSubscriptionEmail = getInitialSubscriptionEmail();
const initialEntryMode = getInitialEntryMode();
const initialSessionId = getInitialSessionId() || buildAnonymousSessionId();
const initialPortfolioPositions = getInitialPortfolioPositions();
const initialTraceRawEnabled = getInitialTraceRawEnabled();
const initialTraceViewMode = getInitialTraceViewMode();
const initialTraceRawShowRawJson = getInitialTraceRawShowRawJson();
applyThemeClass(initialTheme);

interface AppState {
  messages: Message[];
  addMessage: (message: Message) => void;
  updateMessage: (id: string, patch: Partial<Message>) => void;
  updateLastMessage: (content: string) => void;
  removeMessage: (id: string) => void;
  setLoading: (loading: boolean) => void;
  isChatLoading: boolean;
  statusMessage: string | null;
  statusSince: number | null;
  executionProgress: number | null;
  currentStep: string | null;
  setStatus: (message: string | null) => void;
  setExecutionState: (step: string | null, progress?: number | null) => void;
  resetExecutionState: () => void;
  abortController: AbortController | null;
  setAbortController: (controller: AbortController | null) => void;
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
  layoutMode: LayoutMode;
  setLayoutMode: (mode: LayoutMode) => void;
  setDraft: (text: string) => void;
  draft: string;
  subscriptionEmail: string;
  setSubscriptionEmail: (email: string) => void;
  entryMode: EntryMode;
  setEntryMode: (mode: EntryMode) => void;
  sessionId: string;
  setSessionId: (sessionId: string) => void;
  authIdentity: AuthIdentity | null;
  setAuthIdentity: (identity: AuthIdentity | null) => void;
  portfolioPositions: PortfolioPositions;
  setPortfolioPosition: (ticker: string, shares: number) => void;
  removePortfolioPosition: (ticker: string) => void;
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

const WELCOME_MESSAGE: Message = {
  id: 'welcome',
  role: 'assistant',
  content:
    '您好，我是 FinSight AI 金融助手。直接输入股票代码或问题（例如：AAPL 股价走势、特斯拉最新新闻），我会用实时数据和图表帮你分析。',
  timestamp: Date.now(),
};

const MESSAGES_STORAGE_PREFIX = 'finsight-messages:';
const CONVERSATIONS_STORAGE_KEY = 'finsight-conversations';
const MAX_PERSISTED_MESSAGES = 100;
const MAX_CONVERSATIONS = 50;
const memoryMessageStore = new Map<string, string>();
let memoryConversationSummaries: ConversationSummary[] = [];

const messageStorageKey = (sessionId: string): string =>
  `${MESSAGES_STORAGE_PREFIX}${String(sessionId || '').trim()}`;

const normalizePersistedMessages = (raw: string | null): Message[] => {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as Message[];
    if (!Array.isArray(parsed) || parsed.length === 0) return [];
    return parsed.map((m) => ({ ...m, isLoading: false }));
  } catch {
    return [];
  }
};

const normalizeConversationSummaries = (raw: string | null): ConversationSummary[] => {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as ConversationSummary[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => ({
        sessionId: String(item?.sessionId || '').trim(),
        title: String(item?.title || '').trim() || '新对话',
        lastMessagePreview: String(item?.lastMessagePreview || '').trim(),
        messageCount: Math.max(0, Number(item?.messageCount || 0)),
        createdAt: Number(item?.createdAt || Date.now()),
        updatedAt: Number(item?.updatedAt || Date.now()),
      }))
      .filter((item) => item.sessionId)
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_CONVERSATIONS);
  } catch {
    return [];
  }
};

const buildConversationSummary = (
  sessionId: string,
  messages: Message[],
  previous?: ConversationSummary,
): ConversationSummary => {
  const visibleMessages = messages.filter((m) => m.role === 'user' || m.role === 'assistant');
  const nonWelcome = visibleMessages.filter((m) => m.id !== WELCOME_MESSAGE.id && m.content.trim());
  const firstUser = nonWelcome.find((m) => m.role === 'user');
  const latest = [...nonWelcome].reverse()[0] || visibleMessages[visibleMessages.length - 1] || WELCOME_MESSAGE;
  const titleSource = firstUser?.content || latest?.content || previous?.title || '新对话';
  const previewSource = latest?.content || previous?.lastMessagePreview || '';
  const createdAt = previous?.createdAt || visibleMessages[0]?.timestamp || Date.now();
  const updatedAt = latest?.timestamp || previous?.updatedAt || Date.now();

  return {
    sessionId,
    title: titleSource.replace(/\s+/g, ' ').trim().slice(0, 42) || '新对话',
    lastMessagePreview: previewSource.replace(/\s+/g, ' ').trim().slice(0, 90),
    messageCount: nonWelcome.length,
    createdAt,
    updatedAt,
  };
};

const persistConversationSummaries = (summaries: ConversationSummary[]) => {
  const normalized = summaries
    .filter((item) => item.sessionId)
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_CONVERSATIONS);
  if (typeof window === 'undefined') {
    memoryConversationSummaries = normalized;
    return;
  }
  window.localStorage.setItem(CONVERSATIONS_STORAGE_KEY, JSON.stringify(normalized));
};

const loadConversationSummaries = (activeSessionId: string, activeMessages: Message[]): ConversationSummary[] => {
  if (typeof window === 'undefined') {
    const bySession = new Map<string, ConversationSummary>();
    for (const item of memoryConversationSummaries) {
      bySession.set(item.sessionId, item);
    }
    for (const [key, raw] of memoryMessageStore.entries()) {
      if (!key.startsWith(MESSAGES_STORAGE_PREFIX)) continue;
      const sid = key.slice(MESSAGES_STORAGE_PREFIX.length).trim();
      const messages = normalizePersistedMessages(raw);
      if (sid && messages.length) {
        bySession.set(sid, buildConversationSummary(sid, messages, bySession.get(sid)));
      }
    }
    bySession.set(activeSessionId, buildConversationSummary(activeSessionId, activeMessages, bySession.get(activeSessionId)));
    return Array.from(bySession.values())
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_CONVERSATIONS);
  }

  const bySession = new Map<string, ConversationSummary>();
  for (const item of normalizeConversationSummaries(window.localStorage.getItem(CONVERSATIONS_STORAGE_KEY))) {
    bySession.set(item.sessionId, item);
  }

  for (let i = 0; i < window.localStorage.length; i += 1) {
    const key = window.localStorage.key(i);
    if (!key || !key.startsWith(MESSAGES_STORAGE_PREFIX)) continue;
    const sid = key.slice(MESSAGES_STORAGE_PREFIX.length).trim();
    if (!sid) continue;
    const messages = normalizePersistedMessages(window.localStorage.getItem(key));
    if (!messages.length) continue;
    bySession.set(sid, buildConversationSummary(sid, messages, bySession.get(sid)));
  }

  bySession.set(activeSessionId, buildConversationSummary(activeSessionId, activeMessages, bySession.get(activeSessionId)));
  return Array.from(bySession.values())
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_CONVERSATIONS);
};

const upsertConversationSummary = (
  summaries: ConversationSummary[],
  sessionId: string,
  messages: Message[],
): ConversationSummary[] => {
  const sid = String(sessionId || '').trim();
  if (!sid) return summaries;
  const previous = summaries.find((item) => item.sessionId === sid);
  const next = [
    buildConversationSummary(sid, messages, previous),
    ...summaries.filter((item) => item.sessionId !== sid),
  ].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CONVERSATIONS);
  persistConversationSummaries(next);
  return next;
};

const loadMessagesForSession = (sessionId: string): Message[] => {
  const sid = String(sessionId || '').trim();
  if (!sid) return [WELCOME_MESSAGE];
  if (typeof window === 'undefined') {
    const scoped = normalizePersistedMessages(memoryMessageStore.get(messageStorageKey(sid)) || null);
    if (scoped.length > 0) return scoped;
    return [WELCOME_MESSAGE];
  }

  const scoped = normalizePersistedMessages(window.localStorage.getItem(messageStorageKey(sid)));
  if (scoped.length > 0) return scoped;
  return [WELCOME_MESSAGE];
};

const getInitialMessages = (sessionId: string): Message[] => {
  return loadMessagesForSession(sessionId);
};

const persistMessages = (messages: Message[], sessionId: string) => {
  const sid = String(sessionId || '').trim();
  if (!sid) return;
  try {
    const toSave = messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-MAX_PERSISTED_MESSAGES);
    if (typeof window === 'undefined') {
      memoryMessageStore.set(messageStorageKey(sid), JSON.stringify(toSave));
      return;
    }
    window.localStorage.setItem(messageStorageKey(sid), JSON.stringify(toSave));
  } catch {
    // localStorage full or unavailable — silently ignore
  }
};

const clearPersistedMessages = (sessionId: string) => {
  const sid = String(sessionId || '').trim();
  if (!sid) return;
  if (typeof window === 'undefined') {
    memoryMessageStore.delete(messageStorageKey(sid));
    return;
  }
  window.localStorage.removeItem(messageStorageKey(sid));
};

const clearPersistedConversation = (sessionId: string) => {
  const sid = String(sessionId || '').trim();
  if (!sid) return;
  if (typeof window === 'undefined') {
    memoryMessageStore.delete(messageStorageKey(sid));
    return;
  }
  window.localStorage.removeItem(messageStorageKey(sid));
};

const createInitialAgentStatuses = (): Record<AgentLogSource, AgentStatus> => ({
  supervisor: { source: 'supervisor', status: 'idle' },
  router: { source: 'router', status: 'idle' },
  gate: { source: 'gate', status: 'idle' },
  planner: { source: 'planner', status: 'idle' },
  news_agent: { source: 'news_agent', status: 'idle' },
  price_agent: { source: 'price_agent', status: 'idle' },
  fundamental_agent: { source: 'fundamental_agent', status: 'idle' },
  technical_agent: { source: 'technical_agent', status: 'idle' },
  macro_agent: { source: 'macro_agent', status: 'idle' },
  deep_search_agent: { source: 'deep_search_agent', status: 'idle' },
  forum: { source: 'forum', status: 'idle' },
  system: { source: 'system', status: 'idle' },
});

const buildNewConversationSessionId = (identity: AuthIdentity | null): string => {
  if (identity?.userId) {
    const thread = `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    return buildUserSessionId(identity.userId, thread);
  }
  return buildAnonymousSessionId();
};

export const useStore = create<AppState>((set) => ({
  messages: getInitialMessages(initialSessionId),
  conversationSummaries: loadConversationSummaries(initialSessionId, getInitialMessages(initialSessionId)),
  isChatLoading: false,
  statusMessage: null,
  statusSince: null,
  executionProgress: null,
  currentStep: null,
  currentTicker: null,
  abortController: null,
  draft: '',
  theme: initialTheme,
  layoutMode: initialLayout,
  subscriptionEmail: initialSubscriptionEmail,
  entryMode: initialEntryMode,
  sessionId: initialSessionId,
  authIdentity: null,
  portfolioPositions: initialPortfolioPositions,
  // Agent Logs 初始状态
  agentLogs: [],
  agentStatuses: createInitialAgentStatuses(),
  isAgentLogsPanelOpen: true,
  // Raw SSE Events 初始状态
  rawEvents: [],
  isConsoleOpen: true,
  traceRawEnabled: initialTraceRawEnabled,
  traceViewMode: initialTraceViewMode,
  traceRawShowRawJson: initialTraceRawShowRawJson,
  requestMetrics: {
    llmTotalCalls: 0,
    toolTotalCalls: 0,
    updatedAt: null,
  },
  // 右侧面板默认展开
  showRightPanel: true,

  addMessage: (message) =>
    set((state) => {
      const next = [...state.messages, message];
      persistMessages(next, state.sessionId);
      return {
        messages: next,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, state.sessionId, next),
      };
    }),

  updateMessage: (id, patch) =>
    set((state) => {
      const next = state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m));
      // Only persist when message finishes loading (avoid thrashing during streaming)
      if (patch.isLoading === false) persistMessages(next, state.sessionId);
      return {
        messages: next,
        conversationSummaries: patch.isLoading === false
          ? upsertConversationSummary(state.conversationSummaries, state.sessionId, next)
          : state.conversationSummaries,
      };
    }),

  updateLastMessage: (content) =>
    set((state) => {
      if (state.messages.length === 0) return {};
      const next = state.messages.map((m, i) =>
        i === state.messages.length - 1 ? { ...m, content } : m,
      );
      return { messages: next };
    }),

  removeMessage: (id) =>
    set((state) => {
      const next = state.messages.filter((m) => m.id !== id);
      persistMessages(next, state.sessionId);
      return {
        messages: next,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, state.sessionId, next),
      };
    }),

  setLoading: (loading) => set({ isChatLoading: loading }),
  setStatus: (message) =>
    set(() => ({
      statusMessage: message,
      statusSince: message ? Date.now() : null,
    })),
  setExecutionState: (step, progress = null) =>
    set(() => ({
      currentStep: step,
      executionProgress: progress === null ? null : Math.max(0, Math.min(100, progress)),
    })),
  resetExecutionState: () =>
    set(() => ({
      currentStep: null,
      executionProgress: null,
    })),
  setTicker: (ticker) => set({ currentTicker: ticker }),
  setAbortController: (controller) => set({ abortController: controller }),
  cancelChatStream: () =>
    set((state) => {
      state.abortController?.abort();
      return {
        abortController: null,
        isChatLoading: false,
        statusMessage: null,
        statusSince: null,
        currentStep: null,
        executionProgress: null,
      };
    }),
  clearConversationContext: () =>
    set((state) => {
      state.abortController?.abort();
      clearPersistedMessages(state.sessionId);
      const conversationSummaries = upsertConversationSummary(
        state.conversationSummaries,
        state.sessionId,
        [WELCOME_MESSAGE],
      );
      return {
        messages: [WELCOME_MESSAGE],
        conversationSummaries,
        isChatLoading: false,
        statusMessage: null,
        statusSince: null,
        executionProgress: null,
        currentStep: null,
        abortController: null,
        currentTicker: null,
        draft: '',
        agentLogs: [],
        agentStatuses: createInitialAgentStatuses(),
        rawEvents: [],
        requestMetrics: {
          llmTotalCalls: 0,
          toolTotalCalls: 0,
          updatedAt: null,
        },
      };
    }),
  startNewChat: () =>
    set((state) => {
      state.abortController?.abort();
      const nextSessionId = buildNewConversationSessionId(state.authIdentity);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', nextSessionId);
      }
      const conversationSummaries = upsertConversationSummary(
        state.conversationSummaries,
        nextSessionId,
        [WELCOME_MESSAGE],
      );
      return {
        sessionId: nextSessionId,
        messages: [WELCOME_MESSAGE],
        conversationSummaries,
        isChatLoading: false,
        statusMessage: null,
        statusSince: null,
        executionProgress: null,
        currentStep: null,
        abortController: null,
        currentTicker: null,
        draft: '',
        agentLogs: [],
        agentStatuses: createInitialAgentStatuses(),
        rawEvents: [],
        requestMetrics: {
          llmTotalCalls: 0,
          toolTotalCalls: 0,
          updatedAt: null,
        },
      };
    }),

  setTheme: (theme) => {
    set({ theme });
    applyThemeClass(theme);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('finsight-theme', theme);
    }
  },

  setLayoutMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-layout', mode);
      }
      return { layoutMode: mode };
    }),

  setSubscriptionEmail: (email) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-subscription-email', email);
      }
      return { subscriptionEmail: email };
    }),

  setEntryMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-entry-mode', mode);
      }
      return { entryMode: mode };
    }),

  setSessionId: (sessionId) =>
    set((state) => {
      const normalized = String(sessionId || '').trim() || buildAnonymousSessionId();
      const messages = loadMessagesForSession(normalized);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', normalized);
      }
      return {
        sessionId: normalized,
        messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, messages),
      };
    }),

  selectConversation: (sessionId) =>
    set((state) => {
      state.abortController?.abort();
      const normalized = String(sessionId || '').trim();
      if (!normalized) return {};
      const messages = loadMessagesForSession(normalized);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', normalized);
      }
      return {
        sessionId: normalized,
        messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, messages),
        isChatLoading: false,
        statusMessage: null,
        statusSince: null,
        executionProgress: null,
        currentStep: null,
        abortController: null,
        currentTicker: null,
        draft: '',
        agentLogs: [],
        agentStatuses: createInitialAgentStatuses(),
        rawEvents: [],
        requestMetrics: {
          llmTotalCalls: 0,
          toolTotalCalls: 0,
          updatedAt: null,
        },
      };
    }),

  deleteConversation: (sessionId) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized) return {};
      if (normalized === state.sessionId) {
        state.abortController?.abort();
      }
      clearPersistedConversation(normalized);
      const remaining = state.conversationSummaries
        .filter((item) => item.sessionId !== normalized)
        .sort((a, b) => b.updatedAt - a.updatedAt);
      const nextSessionId = normalized === state.sessionId
        ? (remaining[0]?.sessionId || buildNewConversationSessionId(state.authIdentity))
        : state.sessionId;
      const nextMessages = normalized === state.sessionId
        ? loadMessagesForSession(nextSessionId)
        : state.messages;
      const nextSummaries = remaining.length > 0 || nextSessionId === state.sessionId
        ? remaining
        : upsertConversationSummary([], nextSessionId, nextMessages);
      persistConversationSummaries(nextSummaries);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', nextSessionId);
      }
      return {
        sessionId: nextSessionId,
        messages: nextMessages,
        conversationSummaries: nextSummaries,
        isChatLoading: normalized === state.sessionId ? false : state.isChatLoading,
        statusMessage: normalized === state.sessionId ? null : state.statusMessage,
        statusSince: normalized === state.sessionId ? null : state.statusSince,
        executionProgress: normalized === state.sessionId ? null : state.executionProgress,
        currentStep: normalized === state.sessionId ? null : state.currentStep,
        abortController: normalized === state.sessionId ? null : state.abortController,
        currentTicker: normalized === state.sessionId ? null : state.currentTicker,
        draft: normalized === state.sessionId ? '' : state.draft,
        agentLogs: normalized === state.sessionId ? [] : state.agentLogs,
        agentStatuses: normalized === state.sessionId ? createInitialAgentStatuses() : state.agentStatuses,
        rawEvents: normalized === state.sessionId ? [] : state.rawEvents,
      };
    }),

  setAuthIdentity: (identity) =>
    set(() => ({ authIdentity: identity })),

  setPortfolioPosition: (ticker, shares) =>
    set((state) => {
      const key = ticker.trim().toUpperCase();
      if (!key) return {};
      const next = { ...state.portfolioPositions };
      if (!Number.isFinite(shares) || shares <= 0) {
        delete next[key];
      } else {
        next[key] = shares;
      }
      persistPortfolioPositions(next);
      return { portfolioPositions: next };
    }),

  removePortfolioPosition: (ticker) =>
    set((state) => {
      const key = ticker.trim().toUpperCase();
      if (!key) return {};
      if (!state.portfolioPositions[key]) return {};
      const next = { ...state.portfolioPositions };
      delete next[key];
      persistPortfolioPositions(next);
      return { portfolioPositions: next };
    }),

  setDraft: (text) =>
    set(() => ({ draft: text })),

  // Agent Logs Actions
  addAgentLog: (log) =>
    set((state) => ({
      // 保留最近 500 条日志，防止内存溢出
      agentLogs: [...state.agentLogs, log].slice(-500),
    })),

  updateAgentStatus: (source, status) =>
    set((state) => ({
      agentStatuses: {
        ...state.agentStatuses,
        [source]: {
          ...state.agentStatuses[source],
          ...status,
          source,
        },
      },
    })),

  clearAgentLogs: () =>
    set(() => ({
      agentLogs: [],
      agentStatuses: createInitialAgentStatuses(),
    })),

  setAgentLogsPanelOpen: (open) =>
    set(() => ({ isAgentLogsPanelOpen: open })),

  // Raw SSE Events Actions
  addRawEvent: (event) =>
    set((state) => ({
      rawEvents: [...state.rawEvents, event].slice(-1000),
    })),

  clearRawEvents: () =>
    set(() => ({ rawEvents: [] })),

  setConsoleOpen: (open) =>
    set(() => ({ isConsoleOpen: open })),

  setTraceRawEnabled: (enabled) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-trace-raw-enabled', String(Boolean(enabled)));
      }
      return { traceRawEnabled: Boolean(enabled) };
    }),


  setTraceViewMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-trace-view-mode', mode);
      }
      return { traceViewMode: mode };
    }),
  setTraceRawShowRawJson: (show) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-trace-raw-show-json', String(Boolean(show)));
      }
      return { traceRawShowRawJson: Boolean(show) };
    }),

  setRequestMetrics: (metrics) =>
    set((state) => ({
      requestMetrics: {
        ...state.requestMetrics,
        ...metrics,
      },
    })),

  setShowRightPanel: (show) =>
    set(() => ({ showRightPanel: show })),

  toggleRightPanel: () =>
    set((state) => ({ showRightPanel: !state.showRightPanel })),
}));

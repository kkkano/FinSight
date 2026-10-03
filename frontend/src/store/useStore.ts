import { create } from 'zustand';
import type { Message, AgentLogEntry, AgentStatus, AgentLogSource, RawSSEEvent, TraceViewMode } from '../types';
import { apiClient } from '../api/client';
import { buildAuthHeaders } from '../api/http';
import { useModelSelectionStore } from './modelSelection';
import { zh } from '../locales/zh';
import { cancelPersist, flushPersist, schedulePersist } from './persistScheduler';
import type { PendingChatHandoffContext } from '../types/chatHandoff';
import type { RightPanelTab } from '../components/right-panel/types';

type Theme = 'dark' | 'light';
export type ColorConvention = 'intl' | 'cn';
type LayoutMode = 'centered' | 'full';
type ChatStyle = 'bubble' | 'flat';
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

interface ChatSessionStatus {
  statusMessage: string | null;
  statusSince: number | null;
  executionProgress: number | null;
  currentStep: string | null;
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

const getInitialChatStyle = (): ChatStyle => {
  if (typeof window === 'undefined') return 'bubble';
  const stored = window.localStorage.getItem('finsight-chat-style');
  return stored === 'flat' ? 'flat' : 'bubble';
};

const getInitialTheme = (): Theme => {
  if (typeof window === 'undefined') return 'dark';
  const stored = window.localStorage.getItem('finsight-theme');
  if (stored === 'light' || stored === 'dark') return stored;
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  return prefersDark ? 'dark' : 'light';
};

const getInitialColorConvention = (): ColorConvention => {
  if (typeof window === 'undefined') return 'intl';
  return window.localStorage.getItem('finsight-color-convention') === 'cn' ? 'cn' : 'intl';
};

export const normalizePersistedEntryMode = (raw: string | null): EntryMode =>
  raw === 'anonymous' ? 'anonymous' : 'pending';

const getInitialEntryMode = (): EntryMode => {
  if (typeof window === 'undefined') return 'pending';
  return normalizePersistedEntryMode(window.localStorage.getItem('finsight-entry-mode'));
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

export const sessionBelongsToIdentity = (
  sessionId: string | null | undefined,
  identity: AuthIdentity | null,
): boolean => {
  const parts = String(sessionId || '').trim().split(':');
  if (parts.length !== 3) return false;
  const [tenantId, ownerId] = parts;
  if (!ownerId) return false;
  if (!identity?.userId) return tenantId === 'public' && ownerId === 'anonymous';
  return ownerId === normalizeSessionPart(identity.userId, 'user');
};

const sessionsHaveSameOwner = (left: string, right: string): boolean => {
  const leftParts = String(left || '').trim().split(':');
  const rightParts = String(right || '').trim().split(':');
  if (leftParts.length !== 3 || rightParts.length !== 3) return false;
  if (leftParts[1] === 'anonymous' || rightParts[1] === 'anonymous') {
    return leftParts[0] === 'public'
      && rightParts[0] === 'public'
      && leftParts[1] === rightParts[1];
  }
  return Boolean(leftParts[1] && leftParts[1] === rightParts[1]);
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
  if (typeof window === 'undefined') return false;
  const raw = window.localStorage.getItem('finsight-trace-raw-enabled');
  if (raw === null) return false;
  return raw === 'true';
};
const getInitialTraceRawShowRawJson = (): boolean => {
  if (typeof window === 'undefined') return false;
  const raw = window.localStorage.getItem('finsight-trace-raw-show-json');
  if (raw === null) return false;
  return raw === 'true';
};
const getInitialTraceViewMode = (): TraceViewMode => {
  // P2-2: 执行追踪（专家模式）默认可见——这是 FinSight 的护城河
  // （用户关心"AI 怎么得出结论"），不再藏在循环切换的彩蛋里
  if (typeof window === 'undefined') return 'expert';
  const raw = window.localStorage.getItem('finsight-trace-view-mode');
  return raw === 'user' || raw === 'expert' || raw === 'dev' ? (raw as TraceViewMode) : 'expert';
};

const applyThemeClass = (theme: Theme) => {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('light', theme === 'light');
  root.classList.toggle('dark', theme === 'dark');
};

export const applyColorConventionClass = (colorConvention: ColorConvention) => {
  if (typeof document === 'undefined') return;
  document.documentElement.classList.toggle('cn-colors', colorConvention === 'cn');
};

const initialTheme = getInitialTheme();
const initialColorConvention = getInitialColorConvention();
const initialLayout = getInitialLayout();
const initialEntryMode = getInitialEntryMode();
const initialSessionId = getInitialSessionId() || buildAnonymousSessionId();
const initialTraceRawEnabled = getInitialTraceRawEnabled();
const initialTraceViewMode = getInitialTraceViewMode();
const initialTraceRawShowRawJson = getInitialTraceRawShowRawJson();
applyThemeClass(initialTheme);
applyColorConventionClass(initialColorConvention);

interface MessageRecoveryGuard {
  ownerId: string | null;
  runId: string;
  userMessageId: string;
  controller: AbortController;
  timestamp: number;
}

interface AppState {
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
  rightPanelTab: RightPanelTab;
  rightPanelExpanded: boolean;
  setRightPanelTab: (tab: RightPanelTab) => void;
  setRightPanelExpanded: (expanded: boolean) => void;
  openRightPanel: (tab: RightPanelTab, expanded?: boolean) => void;
  setShowRightPanel: (show: boolean) => void;
  toggleRightPanel: () => void;
}

const WELCOME_MESSAGE: Message = {
  id: 'welcome',
  role: 'assistant',
  content:
    zh.chat.welcome,
  timestamp: Date.now(),
};

const MESSAGES_STORAGE_PREFIX = 'finsight-messages:';
const CONVERSATIONS_STORAGE_KEY = 'finsight-conversations';
const MAX_PERSISTED_MESSAGES = 100;
const MAX_CONVERSATIONS = 50;
const memoryMessageStore = new Map<string, string>();
let memoryConversationSummaries: ConversationSummary[] = [];

const serializeBackendMessages = (messages?: Message[]): Array<Record<string, unknown>> => {
  const rows = Array.isArray(messages) ? messages : [];
  return rows
    .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content.trim())
    .slice(-100)
    .map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      timestamp: m.timestamp,
    }));
};

const deriveBackendTitle = (messages?: Message[]): string | undefined => {
  const rows = Array.isArray(messages) ? messages : [];
  const firstUser = rows.find((m) => m.role === 'user' && m.content.trim());
  const source = firstUser?.content || rows.find((m) => m.content.trim())?.content || '';
  return source.replace(/\s+/g, ' ').trim().slice(0, 42) || undefined;
};

const canSyncBackendConversation = (sessionId: string): boolean => {
  const identity = useStore.getState().authIdentity;
  return Boolean(identity?.userId && sessionBelongsToIdentity(sessionId, identity));
};

type ConversationPayload = Parameters<typeof apiClient.createConversation>[1];
interface ConversationSync {
  owner: string;
  pending: ConversationPayload;
  hasPending: boolean;
  running: Promise<void> | null;
  controller: AbortController;
  failed: boolean;
}
const conversationSyncs = new Map<string, ConversationSync>();

const cancelConversationSync = (sessionId: string) => {
  conversationSyncs.get(sessionId)?.controller.abort();
  conversationSyncs.delete(sessionId);
};

const syncBelongsToCurrentUser = (sessionId: string, sync: ConversationSync) =>
  !sync.controller.signal.aborted && conversationSyncs.get(sessionId) === sync
  && useStore.getState().authIdentity?.userId === sync.owner && canSyncBackendConversation(sessionId);

const startConversationSync = (sessionId: string, sync: ConversationSync) => {
  if (sync.running) return;
  // 同会话只发送一个快照，等待期间的新快照合并为最新版本。
  sync.running = Promise.resolve().then(async () => {
    while (sync.hasPending && syncBelongsToCurrentUser(sessionId, sync)) {
      const headers = await buildAuthHeaders();
      if (!headers.Authorization || !syncBelongsToCurrentUser(sessionId, sync)) {
        sync.failed = true;
        return;
      }
      const nextPayload = sync.pending;
      sync.hasPending = false;
      await apiClient.createConversation(sessionId, nextPayload, { headers, signal: sync.controller.signal });
    }
  }).catch(() => {
    sync.failed = true;
  }).finally(() => {
    sync.running = null;
    if (sync.hasPending && !sync.failed && syncBelongsToCurrentUser(sessionId, sync)) startConversationSync(sessionId, sync);
  });
};

const createBackendConversation = (sessionId: string, messages?: Message[]) => {
  if (!sessionId || !canSyncBackendConversation(sessionId)) return;
  const payload = messages
    ? {
        title: deriveBackendTitle(messages),
        messages: serializeBackendMessages(messages),
      }
    : undefined;
  let sync = conversationSyncs.get(sessionId);
  if (!sync) {
    sync = { owner: useStore.getState().authIdentity!.userId, pending: undefined,
      hasPending: false, running: null, controller: new AbortController(), failed: false };
    conversationSyncs.set(sessionId, sync);
  }
  sync.pending = payload;
  sync.hasPending = true;
  sync.failed = false;
  startConversationSync(sessionId, sync);
};

const flushConversationSync = async (sessionId: string): Promise<boolean> => {
  const sync = conversationSyncs.get(sessionId);
  if (!sync) return !canSyncBackendConversation(sessionId);
  while (sync.running) await sync.running;
  return syncBelongsToCurrentUser(sessionId, sync) && !sync.failed && !sync.hasPending;
};

const deleteBackendConversation = (sessionId: string) => {
  if (!sessionId || !canSyncBackendConversation(sessionId)) return;
  void apiClient.deleteConversation(sessionId).catch(() => undefined);
};

const messageStorageKey = (sessionId: string): string =>
  `${MESSAGES_STORAGE_PREFIX}${String(sessionId || '').trim()}`;

const normalizePersistedMessages = (
  raw: string | null,
  options: { preserveLoading?: boolean } = {},
): Message[] => {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as Message[];
    if (!Array.isArray(parsed) || parsed.length === 0) return [];
    const messages = parsed.map((m) => {
      const hasReport = Boolean(m.report?.summary?.trim() || m.report?.synthesis_report?.trim() || m.report?.sections?.length);
      const interrupted = !options.preserveLoading && m.role === 'assistant'
        && (m.isLoading || (!m.content?.trim() && !hasReport));
      return {
        ...m,
        isLoading: options.preserveLoading ? Boolean(m.isLoading) : false,
        ...(interrupted ? { content: m.content?.trim() ? m.content : zh.chat.savedAnswerInterrupted,
          error: zh.chat.savedAnswerInterrupted, canRetry: true } : {}),
      };
    });
    const last = messages.at(-1);
    if (!options.preserveLoading && last?.role === 'user') {
      messages.push({ id: `unanswered:${last.id}`, role: 'assistant', timestamp: last.timestamp + 1,
        content: zh.chat.missingSavedAnswer, error: zh.chat.missingSavedAnswer, canRetry: true, isLoading: false });
    }
    return messages;
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
        title: String(item?.title || '').trim() || zh.chat.newConversation,
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
  const titleSource = firstUser?.content || latest?.content || previous?.title || zh.chat.newConversation;
  const previewSource = latest?.content || previous?.lastMessagePreview || '';
  const createdAt = previous?.createdAt || visibleMessages[0]?.timestamp || Date.now();
  const updatedAt = latest?.timestamp || previous?.updatedAt || Date.now();

  return {
    sessionId,
    title: titleSource.replace(/\s+/g, ' ').trim().slice(0, 42) || zh.chat.newConversation,
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
  try {
    window.localStorage.setItem(CONVERSATIONS_STORAGE_KEY, JSON.stringify(normalized));
  } catch { /* 会话摘要缓存失败不能中断正文更新。 */ }
};

const loadConversationSummaries = (activeSessionId: string, activeMessages: Message[]): ConversationSummary[] => {
  if (typeof window === 'undefined') {
    const bySession = new Map<string, ConversationSummary>();
    for (const item of memoryConversationSummaries) {
      if (!sessionsHaveSameOwner(item.sessionId, activeSessionId)) continue;
      bySession.set(item.sessionId, item);
    }
    for (const [key, raw] of memoryMessageStore.entries()) {
      if (!key.startsWith(MESSAGES_STORAGE_PREFIX)) continue;
      const sid = key.slice(MESSAGES_STORAGE_PREFIX.length).trim();
      if (!sessionsHaveSameOwner(sid, activeSessionId)) continue;
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
    if (!sessionsHaveSameOwner(item.sessionId, activeSessionId)) continue;
    bySession.set(item.sessionId, item);
  }

  for (let i = 0; i < window.localStorage.length; i += 1) {
    const key = window.localStorage.key(i);
    if (!key || !key.startsWith(MESSAGES_STORAGE_PREFIX)) continue;
    const sid = key.slice(MESSAGES_STORAGE_PREFIX.length).trim();
    if (!sid || !sessionsHaveSameOwner(sid, activeSessionId)) continue;
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
  const ownedSummaries = summaries.filter((item) => sessionsHaveSameOwner(item.sessionId, sid));
  const previous = ownedSummaries.find((item) => item.sessionId === sid);
  const next = [
    buildConversationSummary(sid, messages, previous),
    ...ownedSummaries.filter((item) => item.sessionId !== sid),
  ].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_CONVERSATIONS);
  persistConversationSummaries(next);
  return next;
};

const loadMessagesForSession = (
  sessionId: string,
  options: { preserveLoading?: boolean } = {},
): Message[] => {
  const sid = String(sessionId || '').trim();
  if (!sid) return [WELCOME_MESSAGE];
  if (typeof window === 'undefined') {
    const scoped = normalizePersistedMessages(memoryMessageStore.get(messageStorageKey(sid)) || null, options);
    if (scoped.length > 0) return scoped;
    return [WELCOME_MESSAGE];
  }

  const scoped = normalizePersistedMessages(window.localStorage.getItem(messageStorageKey(sid)), options);
  if (scoped.length > 0) return scoped;
  return [WELCOME_MESSAGE];
};

const getInitialMessages = (sessionId: string): Message[] => {
  return loadMessagesForSession(sessionId);
};

/** 本地是否仅有「欢迎语 / 空」——据此判断要不要回后端找回历史。 */
const isEmptyLocalHistory = (messages: Message[]): boolean => {
  if (!messages.length) return true;
  return messages.every((m) => m.id === WELCOME_MESSAGE.id);
};

const needsBackendHistory = (messages: Message[]): boolean => isEmptyLocalHistory(messages)
  || messages.some((message) => message.error === zh.chat.savedAnswerInterrupted || message.error === zh.chat.missingSavedAnswer);

/** 把后端 sanitize 过的消息行（{id, role, content, timestamp}）还原为 Message。 */
const deserializeBackendMessages = (raw: unknown): Message[] => {
  if (!Array.isArray(raw)) return [];
  const out: Message[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const row = item as Record<string, unknown>;
    const role = String(row.role || '').trim();
    const content = String(row.content || '').trim();
    if ((role !== 'user' && role !== 'assistant') || !content) continue;
    out.push({
      id: String(row.id || '') || `srv-${Date.now()}-${out.length}`,
      role: role as Message['role'],
      content,
      timestamp: typeof row.timestamp === 'number' ? row.timestamp : Date.now(),
      runId: typeof row.run_id === 'string' ? row.run_id : undefined,
      replyTo: typeof row.reply_to === 'string' ? row.reply_to : undefined,
      isLoading: row.isLoading === true || row.answer_status === 'running',
      canRetry: row.canRetry === true,
      report: row.report && typeof row.report === 'object' ? row.report as Message['report'] : undefined,
      ...(row.error ? { error: String(row.error), canRetry: row.canRetry === true } : {}),
    });
  }
  return out;
};

/**
 * 恢复空历史或未保存的回答；只替换同一问题的已完成快照，不覆盖新消息或正在生成的内容。
 */
const hydrateMessagesFromBackend = (sessionId: string): void => {
  const sid = String(sessionId || '').trim();
  if (!sid || !canSyncBackendConversation(sid)) return;
  const originalMessages = useStore.getState().messages;
  recoverPendingRun(sid);
  void apiClient
    .getConversation(sid)
    .then((resp) => {
      const conversation = resp?.conversation as Record<string, unknown> | undefined;
      const restored = deserializeBackendMessages(conversation?.messages);
      if (!restored.length) return;

      const state = useStore.getState();
      if (state.sessionId !== sid || state.messages !== originalMessages || state.chatLoadingBySession[sid]) return;
      if (!isEmptyLocalHistory(state.messages)) {
        const lastUser = [...state.messages].reverse().find((message) => message.role === 'user');
        const index = restored.findIndex((message) => message.role === 'user' && message.id === lastUser?.id);
        const answer = restored[index + 1];
        if (index < 0 || answer?.role !== 'assistant'
          || answer.content === zh.chat.savedAnswerInterrupted || answer.content === zh.chat.missingSavedAnswer) return;
      }

      const localById = new Map(state.messages.map((message) => [message.id, message]));
      const recovered = restored.map((message) => ({ ...localById.get(message.id), ...message,
        isLoading: false, error: undefined, canRetry: false }));
      persistMessages(recovered, sid, { syncBackend: false });
      useStore.setState({
        messages: recovered,
        conversationSummaries: upsertConversationSummary(
          state.conversationSummaries,
          sid,
          recovered,
        ),
      });
      recoverPendingRun(sid);
    })
    .catch(() => undefined);
};

const recoverPendingRun = (sessionId: string): void => {
  const initial = useStore.getState();
  if (initial.sessionId !== sessionId || initial.chatLoadingBySession[sessionId] || !initial.authIdentity) return;
  const pending = [...initial.messages].reverse().find((message) => message.role === 'assistant'
    && message.runId && (message.error === zh.chat.savedAnswerInterrupted || message.isLoading));
  if (!pending?.runId) return;
  const runId = pending.runId;
  const owner = initial.authIdentity.userId;
  const controller = new AbortController();
  initial.setSessionLoading(sessionId, true);
  initial.setSessionAbortController(sessionId, controller);
  initial.setStatus(zh.chat.recoveringAnswer);
  const stillOwned = () => useStore.getState().authIdentity?.userId === owner && !controller.signal.aborted;
  void (async () => {
    try {
      while (stillOwned()) {
        const run = await apiClient.getExecutionRun(runId, controller.signal);
        if (!stillOwned()) return;
        const result = run.result;
        if (run.status !== 'running') {
          const message = result?.assistant_message;
          const content = typeof message?.content === 'string' ? message.content
            : typeof result?.response === 'string' ? result.response : zh.chat.savedAnswerInterrupted;
          const completed = result?.type === 'done' && run.status === 'completed';
          useStore.getState().updateMessageInSession(sessionId, pending.id, {
            id: run.assistant_message_id || pending.id, content, isLoading: false,
            report: message?.report || result?.report || result?.blocked_report,
            error: completed ? undefined : String(message?.error || content),
            canRetry: !completed || message?.canRetry === true || result?.quality_blocked === true,
          }, { syncBackend: false });
          return;
        }
        await new Promise<void>((resolve) => {
          const timer = setTimeout(() => { controller.signal.removeEventListener('abort', stop); resolve(); }, 1500);
          const stop = () => { clearTimeout(timer); resolve(); };
          controller.signal.addEventListener('abort', stop, { once: true });
        });
      }
    } catch {
      // 网络暂不可用时保留已有正文和重试入口，下一次打开继续恢复同一 run。
    } finally {
      const current = useStore.getState();
      if (current.authIdentity?.userId === owner && current.abortControllersBySession[sessionId] === controller) {
        current.setSessionLoading(sessionId, false);
        current.setSessionAbortController(sessionId, null);
      }
    }
  })();
};

const persistMessages = (
  messages: Message[],
  sessionId: string,
  options: { syncBackend?: boolean } = {},
) => {
  const sid = String(sessionId || '').trim();
  if (!sid) return;
  const syncBackend = options.syncBackend !== false;
  const toSave = messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .slice(-MAX_PERSISTED_MESSAGES);
  try {
    if (typeof window === 'undefined') {
      memoryMessageStore.set(messageStorageKey(sid), JSON.stringify(toSave));
    } else {
      window.localStorage.setItem(messageStorageKey(sid), JSON.stringify(toSave));
    }
  } catch {
    // 容量不足时优先保存正文，调试轨迹仍留在当前页面内存中。
    try {
      window.localStorage.setItem(messageStorageKey(sid), JSON.stringify(toSave.map(
        ({ id, role, content, timestamp, isLoading, error, canRetry }) => ({ id, role, content, timestamp, isLoading, error, canRetry }),
      )));
    } catch { /* 后端同步不依赖本地存储是否可用。 */ }
  }
  if (syncBackend) createBackendConversation(sid, toSave);
};

const appendMessageForSession = (messages: Message[], message: Message): Message[] => {
  return [...messages, message];
};

const patchMessageForSession = (
  messages: Message[],
  id: string,
  patch: Partial<Message>,
): Message[] => {
  return messages.map((m) => (m.id === id ? { ...m, ...patch } : m));
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

const ownedSessionOrFallback = (
  sessionId: string | null | undefined,
  identity: AuthIdentity | null,
): string => {
  const candidate = String(sessionId || '').trim();
  if (candidate && sessionBelongsToIdentity(candidate, identity)) return candidate;
  return identity?.userId ? buildUserSessionId(identity.userId) : buildAnonymousSessionId();
};

const EMPTY_CHAT_SESSION_STATUS: ChatSessionStatus = {
  statusMessage: null,
  statusSince: null,
  executionProgress: null,
  currentStep: null,
};

const statusForSession = (
  statuses: Record<string, ChatSessionStatus>,
  sessionId: string,
): ChatSessionStatus => statuses[sessionId] || EMPTY_CHAT_SESSION_STATUS;

export const useStore = create<AppState>((set) => ({
  messages: getInitialMessages(initialSessionId),
  conversationSummaries: loadConversationSummaries(initialSessionId, getInitialMessages(initialSessionId)),
  isChatLoading: false,
  chatLoadingBySession: {},
  chatStatusBySession: {},
  statusMessage: null,
  statusSince: null,
  executionProgress: null,
  currentStep: null,
  currentTicker: null,
  abortController: null,
  abortControllersBySession: {},
  draft: '',
  draftBySession: {},
  pendingChatHandoffContextBySession: {},
  theme: initialTheme,
  colorConvention: initialColorConvention,
  layoutMode: initialLayout,
  chatStyle: getInitialChatStyle(),
  entryMode: initialEntryMode,
  sessionId: initialSessionId,
  authIdentity: null,
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
  // 右侧市场与执行面板默认收起，按需展开。
  showRightPanel: false,
  rightPanelTab: 'chart',
  rightPanelExpanded: false,

  addMessage: (message) =>
    set((state) => {
      const next = appendMessageForSession(state.messages, message);
      persistMessages(next, state.sessionId);
      return {
        messages: next,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, state.sessionId, next),
      };
    }),

  addMessageToSession: (sessionId, message) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const baseMessages = normalized === state.sessionId
        ? state.messages
        : loadMessagesForSession(normalized);
      const next = appendMessageForSession(baseMessages, message);
      persistMessages(next, normalized);
      return {
        messages: normalized === state.sessionId ? next : state.messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, next),
      };
    }),

  updateMessage: (id, patch) =>
    set((state) => {
      const next = patchMessageForSession(state.messages, id, patch);
      const finalized = patch.isLoading === false;
      if (!finalized) {
        // FE-01：流式中间态的写盘与摘要更新去抖合并，消息 state 照常更新
        schedulePersist(state.sessionId, () => {
          const latest = useStore.getState();
          if (latest.sessionId !== state.sessionId) return; // 已切会话，等收尾路径落盘
          persistMessages(latest.messages, latest.sessionId, { syncBackend: false });
          useStore.setState({
            conversationSummaries: upsertConversationSummary(
              latest.conversationSummaries,
              latest.sessionId,
              latest.messages,
            ),
          });
        });
        return { messages: next };
      }
      cancelPersist(state.sessionId);
      persistMessages(next, state.sessionId, { syncBackend: true });
      return {
        messages: next,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, state.sessionId, next),
      };
    }),

  updateMessageInSession: (sessionId, id, patch, options = {}) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const isActiveSession = normalized === state.sessionId;
      let baseMessages = isActiveSession
        ? state.messages
        : loadMessagesForSession(normalized, { preserveLoading: Boolean(state.chatLoadingBySession[normalized]) });
      const recovery = options.recovery;
      if (recovery && (recovery.controller.signal.aborted
          || (state.authIdentity?.userId || null) !== recovery.ownerId
          || state.abortControllersBySession[normalized] !== recovery.controller
          || !state.chatLoadingBySession[normalized]
          || !baseMessages.some((message) => message.id === recovery.userMessageId && message.role === 'user'))) return {};
      let targetId = id;
      if (!baseMessages.some((message) => message.id === targetId)) {
        // 只有仍拥有问题和 AbortController 的本轮正文可恢复；图表等补挂不传此守卫。
        if (!recovery || !patch.content?.trim()) return {};
        const counterpart = baseMessages.find((message) => message.role === 'assistant'
          && message.replyTo === recovery.userMessageId);
        if (counterpart) {
          if (counterpart.runId !== recovery.runId) return {};
          targetId = counterpart.id;
        } else {
          baseMessages = [...baseMessages, { id, role: 'assistant', content: '', timestamp: recovery.timestamp,
            runId: recovery.runId, replyTo: recovery.userMessageId, isLoading: true }];
        }
      }
      if (recovery && baseMessages.some((message) => message.id === targetId
        && (message.role !== 'assistant' || message.runId !== recovery.runId || message.replyTo !== recovery.userMessageId))) return {};
      const next = patchMessageForSession(baseMessages, targetId, patch);
      const finalized = patch.isLoading === false;
      if (!finalized && isActiveSession) {
        // FE-01：流式中间态去抖（仅当前会话；跨会话更新低频，保持原直写路径）
        schedulePersist(normalized, () => {
          const latest = useStore.getState();
          if (latest.sessionId !== normalized) return; // 已切走：patch 含全量 content，收尾路径会补齐
          persistMessages(latest.messages, normalized, { syncBackend: false });
          useStore.setState({
            conversationSummaries: upsertConversationSummary(latest.conversationSummaries, normalized, latest.messages),
          });
        });
        return { messages: next };
      }
      if (finalized) cancelPersist(normalized);
      persistMessages(next, normalized, { syncBackend: finalized && options.syncBackend !== false });
      return {
        messages: isActiveSession ? next : state.messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, next),
      };
    }),

  flushConversationSync,

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

  setLoading: (loading) =>
    set((state) => ({
      isChatLoading: loading,
      chatLoadingBySession: {
        ...state.chatLoadingBySession,
        [state.sessionId]: loading,
      },
    })),
  setSessionLoading: (sessionId, loading) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const nextStatuses = loading
        ? state.chatStatusBySession
        : {
            ...state.chatStatusBySession,
            [normalized]: EMPTY_CHAT_SESSION_STATUS,
          };
      return {
        chatLoadingBySession: {
          ...state.chatLoadingBySession,
          [normalized]: loading,
        },
        chatStatusBySession: nextStatuses,
        isChatLoading: normalized === state.sessionId ? loading : state.isChatLoading,
        statusMessage: normalized === state.sessionId && !loading ? null : state.statusMessage,
        statusSince: normalized === state.sessionId && !loading ? null : state.statusSince,
        executionProgress: normalized === state.sessionId && !loading ? null : state.executionProgress,
        currentStep: normalized === state.sessionId && !loading ? null : state.currentStep,
      };
    }),
  setStatus: (message) =>
    set((state) => {
      const nextStatus = {
        ...statusForSession(state.chatStatusBySession, state.sessionId),
        statusMessage: message,
        statusSince: message ? Date.now() : null,
      };
      return {
        statusMessage: nextStatus.statusMessage,
        statusSince: nextStatus.statusSince,
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: nextStatus,
        },
      };
    }),
  setExecutionState: (step, progress = null) =>
    set((state) => {
      const nextProgress = progress === null ? null : Math.max(0, Math.min(100, progress));
      const nextStatus = {
        ...statusForSession(state.chatStatusBySession, state.sessionId),
        currentStep: step,
        executionProgress: nextProgress,
      };
      return {
        currentStep: step,
        executionProgress: nextProgress,
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: nextStatus,
        },
      };
    }),
  resetExecutionState: () =>
    set((state) => {
      const nextStatus = {
        ...statusForSession(state.chatStatusBySession, state.sessionId),
        currentStep: null,
        executionProgress: null,
      };
      return {
        currentStep: null,
        executionProgress: null,
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: nextStatus,
        },
      };
    }),
  setTicker: (ticker) => set({ currentTicker: ticker }),
  setAbortController: (controller) =>
    set((state) => ({
      abortController: controller,
      abortControllersBySession: {
        ...state.abortControllersBySession,
        [state.sessionId]: controller,
      },
    })),
  setSessionAbortController: (sessionId, controller) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      return {
        abortControllersBySession: {
          ...state.abortControllersBySession,
          [normalized]: controller,
        },
        abortController: normalized === state.sessionId ? controller : state.abortController,
      };
    }),
  cancelChatStream: () =>
    set((state) => {
      const progress = state.executionProgress;
      const activeController = state.abortControllersBySession[state.sessionId] || state.abortController;
      activeController?.abort();
      return {
        abortController: null,
        abortControllersBySession: {
          ...state.abortControllersBySession,
          [state.sessionId]: null,
        },
        chatLoadingBySession: {
          ...state.chatLoadingBySession,
          [state.sessionId]: false,
        },
        isChatLoading: false,
        statusMessage: zh.chat.stopped,
        statusSince: Date.now(),
        currentStep: zh.chat.stoppedLabel,
        executionProgress: progress,
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: {
            statusMessage: zh.chat.stopped,
            statusSince: Date.now(),
            currentStep: zh.chat.stoppedLabel,
            executionProgress: progress,
          },
        },
      };
    }),
  clearConversationContext: () =>
    set((state) => {
      const activeController = state.abortControllersBySession[state.sessionId] || state.abortController;
      activeController?.abort();
      clearPersistedMessages(state.sessionId);
      createBackendConversation(state.sessionId, [WELCOME_MESSAGE]);
      const conversationSummaries = upsertConversationSummary(
        state.conversationSummaries,
        state.sessionId,
        [WELCOME_MESSAGE],
      );
      return {
        messages: [WELCOME_MESSAGE],
        conversationSummaries,
        isChatLoading: false,
        chatLoadingBySession: {
          ...state.chatLoadingBySession,
          [state.sessionId]: false,
        },
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [state.sessionId]: EMPTY_CHAT_SESSION_STATUS,
        },
        statusMessage: null,
        statusSince: null,
        executionProgress: null,
        currentStep: null,
        abortController: null,
        abortControllersBySession: {
          ...state.abortControllersBySession,
          [state.sessionId]: null,
        },
        currentTicker: null,
        draft: '',
        draftBySession: {
          ...state.draftBySession,
          [state.sessionId]: '',
        },
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
  startNewChat: () => {
    // FE-01：切走前把当前会话 pending 的去抖写盘落定（此刻 state 仍指向旧会话，能正确落盘）
    flushPersist(useStore.getState().sessionId);
    return set((state) => {
      const nextSessionId = buildNewConversationSessionId(state.authIdentity);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', nextSessionId);
      }
      createBackendConversation(nextSessionId, [WELCOME_MESSAGE]);
      const conversationSummaries = upsertConversationSummary(
        state.conversationSummaries,
        nextSessionId,
        [WELCOME_MESSAGE],
      );
      const sessionStatus = statusForSession(state.chatStatusBySession, nextSessionId);
      return {
        sessionId: nextSessionId,
        messages: [WELCOME_MESSAGE],
        conversationSummaries,
        isChatLoading: Boolean(state.chatLoadingBySession[nextSessionId]),
        statusMessage: sessionStatus.statusMessage,
        statusSince: sessionStatus.statusSince,
        executionProgress: sessionStatus.executionProgress,
        currentStep: sessionStatus.currentStep,
        abortController: state.abortControllersBySession[nextSessionId] || null,
        currentTicker: null,
        draft: state.draftBySession[nextSessionId] || '',
        agentLogs: [],
        agentStatuses: createInitialAgentStatuses(),
        rawEvents: [],
        requestMetrics: {
          llmTotalCalls: 0,
          toolTotalCalls: 0,
          updatedAt: null,
        },
      };
    });
  },

  setTheme: (theme) => {
    set({ theme });
    applyThemeClass(theme);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('finsight-theme', theme);
    }
  },

  setColorConvention: (colorConvention) => {
    set({ colorConvention });
    applyColorConventionClass(colorConvention);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('finsight-color-convention', colorConvention);
    }
  },

  setLayoutMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-layout', mode);
      }
      return { layoutMode: mode };
    }),

  setChatStyle: (style) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-chat-style', style);
      }
      return { chatStyle: style };
    }),

  setEntryMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-entry-mode', mode);
      }
      return { entryMode: mode };
    }),

  setSessionId: (sessionId) => {
    let needHydrate = false;
    let hydrateSid = '';
    set((state) => {
      const normalized = ownedSessionOrFallback(sessionId, state.authIdentity);
      const messages = loadMessagesForSession(normalized, { preserveLoading: Boolean(state.chatLoadingBySession[normalized]) });
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', normalized);
      }
      // 空历史或中断回答只读取服务器快照，不能用旧本地内容覆盖它。
      if (needsBackendHistory(messages) && !state.chatLoadingBySession[normalized]) {
        needHydrate = true;
        hydrateSid = normalized;
      }
      const sessionStatus = statusForSession(state.chatStatusBySession, normalized);
      return {
        sessionId: normalized,
        messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, messages),
        isChatLoading: Boolean(state.chatLoadingBySession[normalized]),
        statusMessage: sessionStatus.statusMessage,
        statusSince: sessionStatus.statusSince,
        executionProgress: sessionStatus.executionProgress,
        currentStep: sessionStatus.currentStep,
        abortController: state.abortControllersBySession[normalized] || null,
        draft: state.draftBySession[normalized] || '',
      };
    });
    if (needHydrate) hydrateMessagesFromBackend(hydrateSid);
  },

  selectConversation: (sessionId) => {
    // FE-01：切走前先把旧会话的 pending 去抖写盘落定，防止读到半新半旧
    flushPersist(useStore.getState().sessionId);
    let needHydrate = false;
    let hydrateSid = '';
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const messages = loadMessagesForSession(normalized, { preserveLoading: Boolean(state.chatLoadingBySession[normalized]) });
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', normalized);
      }
      if (needsBackendHistory(messages) && !state.chatLoadingBySession[normalized]) {
        needHydrate = true;
        hydrateSid = normalized;
      }
      const sessionStatus = statusForSession(state.chatStatusBySession, normalized);
      return {
        sessionId: normalized,
        messages,
        conversationSummaries: upsertConversationSummary(state.conversationSummaries, normalized, messages),
        isChatLoading: Boolean(state.chatLoadingBySession[normalized]),
        statusMessage: sessionStatus.statusMessage,
        statusSince: sessionStatus.statusSince,
        executionProgress: sessionStatus.executionProgress,
        currentStep: sessionStatus.currentStep,
        abortController: state.abortControllersBySession[normalized] || null,
        currentTicker: null,
        draft: state.draftBySession[normalized] || '',
        agentLogs: [],
        agentStatuses: createInitialAgentStatuses(),
        rawEvents: [],
        requestMetrics: {
          llmTotalCalls: 0,
          toolTotalCalls: 0,
          updatedAt: null,
        },
      };
    });
    if (needHydrate) hydrateMessagesFromBackend(hydrateSid);
  },

  deleteConversation: (sessionId) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (!normalized || !sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      if (normalized === state.sessionId) {
        const activeController = state.abortControllersBySession[normalized] || state.abortController;
        activeController?.abort();
      }
      cancelPersist(normalized); // FE-01：丢弃 pending 写盘，防止定时器把已删会话写回
      cancelConversationSync(normalized);
      deleteBackendConversation(normalized);
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
      if (normalized === state.sessionId && nextSessionId !== normalized) {
        createBackendConversation(nextSessionId, nextMessages);
      }
      const nextSessionStatus = statusForSession(state.chatStatusBySession, nextSessionId);
      const pendingChatHandoffContextBySession = { ...state.pendingChatHandoffContextBySession };
      delete pendingChatHandoffContextBySession[normalized];
      return {
        sessionId: nextSessionId,
        messages: nextMessages,
        conversationSummaries: nextSummaries,
        isChatLoading: normalized === state.sessionId ? Boolean(state.chatLoadingBySession[nextSessionId]) : state.isChatLoading,
        chatLoadingBySession: {
          ...state.chatLoadingBySession,
          [normalized]: false,
        },
        chatStatusBySession: {
          ...state.chatStatusBySession,
          [normalized]: EMPTY_CHAT_SESSION_STATUS,
        },
        statusMessage: normalized === state.sessionId ? nextSessionStatus.statusMessage : state.statusMessage,
        statusSince: normalized === state.sessionId ? nextSessionStatus.statusSince : state.statusSince,
        executionProgress: normalized === state.sessionId ? nextSessionStatus.executionProgress : state.executionProgress,
        currentStep: normalized === state.sessionId ? nextSessionStatus.currentStep : state.currentStep,
        abortController: normalized === state.sessionId ? (state.abortControllersBySession[nextSessionId] || null) : state.abortController,
        abortControllersBySession: {
          ...state.abortControllersBySession,
          [normalized]: null,
        },
        currentTicker: normalized === state.sessionId ? null : state.currentTicker,
        draft: normalized === state.sessionId ? (state.draftBySession[nextSessionId] || '') : state.draft,
        draftBySession: {
          ...state.draftBySession,
          [normalized]: '',
        },
        pendingChatHandoffContextBySession,
        agentLogs: normalized === state.sessionId ? [] : state.agentLogs,
        agentStatuses: normalized === state.sessionId ? createInitialAgentStatuses() : state.agentStatuses,
        rawEvents: normalized === state.sessionId ? [] : state.rawEvents,
      };
    }),

  setAuthIdentity: (identity) => {
    set((state) => {
      const normalizedIdentity = identity?.userId
        ? { userId: String(identity.userId).trim(), email: identity.email }
        : null;
      const currentUserId = String(state.authIdentity?.userId || '').trim();
      const nextUserId = String(normalizedIdentity?.userId || '').trim();
      useModelSelectionStore.getState().setUser(nextUserId || null);
      if (currentUserId === nextUserId) return { authIdentity: normalizedIdentity };

      for (const sessionId of conversationSyncs.keys()) cancelConversationSync(sessionId);

      for (const controller of Object.values(state.abortControllersBySession)) {
        controller?.abort();
      }
      state.abortController?.abort();
      const priorSessionIds = new Set([
        state.sessionId,
        ...state.conversationSummaries.map((item) => item.sessionId),
        ...Object.keys(state.chatLoadingBySession),
      ]);
      for (const priorSessionId of priorSessionIds) cancelPersist(priorSessionId);

      const nextSessionId = normalizedIdentity?.userId
        ? (sessionBelongsToIdentity(state.sessionId, normalizedIdentity)
          ? state.sessionId : buildUserSessionId(normalizedIdentity.userId))
        : buildAnonymousSessionId();
      const nextMessages = loadMessagesForSession(nextSessionId);
      const nextSummaries = loadConversationSummaries(nextSessionId, nextMessages);
      persistConversationSummaries(nextSummaries);
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-session-id', nextSessionId);
      }

      return {
        authIdentity: normalizedIdentity,
        sessionId: nextSessionId,
        messages: nextMessages,
        conversationSummaries: nextSummaries,
        isChatLoading: false,
        chatLoadingBySession: {},
        chatStatusBySession: {},
        statusMessage: null,
        statusSince: null,
        executionProgress: null,
        currentStep: null,
        abortController: null,
        abortControllersBySession: {},
        currentTicker: null,
        draft: '',
        draftBySession: {},
        pendingChatHandoffContextBySession: {},
        agentLogs: [],
        agentStatuses: createInitialAgentStatuses(),
        rawEvents: [],
        requestMetrics: {
          llmTotalCalls: 0,
          toolTotalCalls: 0,
          updatedAt: null,
        },
      };
    });
    const current = useStore.getState();
    if (current.authIdentity?.userId && needsBackendHistory(current.messages)
      && !current.chatLoadingBySession[current.sessionId]) hydrateMessagesFromBackend(current.sessionId);
  },

  setDraft: (text) =>
    set((state) => ({
      draft: text,
      draftBySession: {
        ...state.draftBySession,
        [state.sessionId]: text,
      },
    })),

  setPendingChatHandoffContext: (sessionId, value) =>
    set((state) => {
      const normalized = String(sessionId || '').trim();
      if (
        !normalized
        || value.sessionId !== normalized
        || !sessionBelongsToIdentity(normalized, state.authIdentity)
      ) return {};
      return {
        pendingChatHandoffContextBySession: {
          ...state.pendingChatHandoffContextBySession,
          [normalized]: value,
        },
      };
    }),

  takePendingChatHandoffContext: (sessionId) => {
    const normalized = String(sessionId || '').trim();
    if (!normalized) return undefined;
    let taken: PendingChatHandoffContext | undefined;
    set((state) => {
      if (!sessionBelongsToIdentity(normalized, state.authIdentity)) return {};
      const candidate = state.pendingChatHandoffContextBySession[normalized];
      if (!candidate || candidate.sessionId !== normalized) return {};
      taken = candidate;
      const next = { ...state.pendingChatHandoffContextBySession };
      delete next[normalized];
      return { pendingChatHandoffContextBySession: next };
    });
    return taken;
  },

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
    set((state) => ({ showRightPanel: show, rightPanelExpanded: show && state.rightPanelExpanded })),

  setRightPanelTab: (rightPanelTab) => set({ rightPanelTab }),
  setRightPanelExpanded: (rightPanelExpanded) => set({ rightPanelExpanded }),
  openRightPanel: (rightPanelTab, rightPanelExpanded = false) => set({ showRightPanel: true, rightPanelTab, rightPanelExpanded }),

  toggleRightPanel: () =>
    set((state) => ({ showRightPanel: !state.showRightPanel })),
}));

// FE-01：页面卸载前把所有 pending 的去抖写盘落定，避免丢最后 ≤500ms 的流式内容
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => flushPersist());
}

import type { StoreApi } from 'zustand';
import type { Message } from '../types';
import type { AppState, ConversationSummary } from './stateTypes';
import { publicResearchBlocks } from './researchStream';
import { apiClient } from '../api/client';
import { buildAuthHeaders } from '../api/http';
import { zh } from '../locales/zh';
import { extractTickers } from '../utils/ticker';
import { sessionBelongsToIdentity, sessionsHaveSameOwner } from './sessionIdentity';

/** 后端同步与本地恢复共享同一个set/get闭包，模块不反向导入组合store。 */
export const createConversationServices = (setState: StoreApi<AppState>['setState'], getState: () => AppState) => {
  const useStore = { getState, setState };
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
          title: String(item?.title || '').trim().slice(0, 20) || zh.chat.newConversation,
          tickers: Array.isArray(item?.tickers) ? item.tickers : [],
          runStatus: item?.runStatus,
          answerStatus: item?.answerStatus,
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
    const lastAnswer = [...messages].reverse().find((message) => message.role === 'assistant' && message.id !== WELCOME_MESSAGE.id);
  
    return {
      sessionId,
      title: titleSource.replace(/\s+/g, ' ').trim().slice(0, 20) || zh.chat.newConversation,
      tickers: [...new Set(messages.filter((message) => message.role === 'user').flatMap((message) => extractTickers(message.content)))],
      runStatus: lastAnswer?.isLoading ? 'running' : lastAnswer?.runStatus || (lastAnswer?.error ? 'failed' : undefined),
      answerStatus: lastAnswer?.answerStatus,
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
      const content = String(row.content || '');
      if ((role !== 'user' && role !== 'assistant') || (!content.trim() && role === 'user')) continue;
      // 历史快照不是实时运行凭据；先停下旧计时，再按run接口确认真实状态。
      const pending = role === 'assistant' && (row.isLoading === true || row.answer_status === 'running'
        || row.run_status === 'running' || (!content.trim() && !row.report));
      const placeholder = !content.trim() || /^正在生成回答[.…\s]*$/.test(content);
      out.push({
        id: String(row.id || '') || `srv-${Date.now()}-${out.length}`,
        role: role as Message['role'],
        content: pending && placeholder ? zh.chat.savedAnswerInterrupted : content,
        timestamp: typeof row.timestamp === 'number' ? row.timestamp : Date.now(),
        runId: typeof row.run_id === 'string' ? row.run_id : undefined,
        ...(Array.isArray(row.blocks) ? { blocks: publicResearchBlocks(row.blocks) } : {}),
        ...(row.review_revision && typeof row.review_revision === 'object'
          ? { reviewRevision: row.review_revision as Message['reviewRevision'] } : {}),
        thinking: Array.isArray(row.thinking) ? row.thinking : undefined,
        evidence_pool: Array.isArray(row.evidence_pool) ? row.evidence_pool : undefined,
        priceLevels: Array.isArray(row.price_levels) ? row.price_levels : undefined,
        runStatus: typeof row.run_status === 'string' ? row.run_status : undefined,
        answerStatus: typeof row.answer_status === 'string' ? row.answer_status : undefined,
        replyTo: typeof row.reply_to === 'string' ? row.reply_to : undefined,
        isLoading: false,
        canRetry: pending || row.canRetry === true,
        report: row.report && typeof row.report === 'object' ? row.report as Message['report'] : undefined,
        ...(row.error ? { error: String(row.error), canRetry: row.canRetry === true } : {}),
        ...(pending ? { error: zh.chat.savedAnswerInterrupted, canRetry: true } : {}),
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
    const ownerId = useStore.getState().authIdentity?.userId;
    const originalMessages = useStore.getState().messages;
    recoverPendingRun(sid);
    void apiClient
      .getConversation(sid)
      .then((resp) => {
        const conversation = resp?.conversation as Record<string, unknown> | undefined;
        let restored = deserializeBackendMessages(conversation?.messages);
        if (!restored.length) return;
  
        const state = useStore.getState();
        if (state.authIdentity?.userId !== ownerId || !canSyncBackendConversation(sid)
          || (resp.session_id && resp.session_id !== sid)
          || state.sessionId !== sid || state.messages !== originalMessages || state.chatLoadingBySession[sid]) return;
        if (!isEmptyLocalHistory(state.messages)) {
          const lastUser = [...state.messages].reverse().find((message) => message.role === 'user');
          const index = restored.findIndex((message) => message.role === 'user' && message.id === lastUser?.id);
          if (index < 0 || restored[index].content !== lastUser?.content) return;
          let answer = restored[index + 1];
          if (answer?.role === 'user') {
            // 旧客户端缺少消息 ID 时，服务器在同文旧问题后写入带 run 绑定的标准问题/回答。
            // 尾部必须全部是同文、已完成且逐轮绑定的配对；保留每个真实 run，只合并旧副本。
            const tail = restored.slice(index + 1);
            if (lastUser?.runId || restored[index].runId || tail.length < 2 || tail.length % 2 !== 0) return;
            for (let offset = 0; offset < tail.length; offset += 2) {
              const canonicalUser = tail[offset];
              const canonicalAnswer = tail[offset + 1];
              if (canonicalUser.role !== 'user' || canonicalUser.id === lastUser?.id
                || canonicalUser.content !== lastUser?.content || !canonicalUser.runId
                || canonicalAnswer.role !== 'assistant' || canonicalAnswer.runId !== canonicalUser.runId
                || canonicalAnswer.replyTo !== canonicalUser.id || canonicalAnswer.isLoading || canonicalAnswer.error
                || canonicalAnswer.content === zh.chat.savedAnswerInterrupted
                || canonicalAnswer.content === zh.chat.missingSavedAnswer) return;
            }
            answer = tail[1];
            restored = [...restored.slice(0, index), ...restored.slice(index + 1)];
          }
          if (index < 0 || answer?.role !== 'assistant'
            || (!answer.runId && (answer.content === zh.chat.savedAnswerInterrupted || answer.content === zh.chat.missingSavedAnswer))) return;
        }
  
        const localById = new Map(state.messages.map((message) => [message.id, message]));
        const recovered = restored.map((message) => ({ ...localById.get(message.id), ...message, error: message.error }));
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
    const pendingMessages = [...initial.messages].reverse().filter((message) => message.role === 'assistant'
      && message.runId && (message.error === zh.chat.savedAnswerInterrupted || message.isLoading));
    if (!pendingMessages.length) return;
    const owner = initial.authIdentity.userId;
    const controller = new AbortController();
    initial.setSessionLoading(sessionId, true);
    initial.setSessionAbortController(sessionId, controller);
    initial.setStatus(zh.chat.recoveringAnswer);
    const stillOwned = () => useStore.getState().authIdentity?.userId === owner && !controller.signal.aborted;
    void (async () => {
      try {
        for (const pending of pendingMessages) {
          const runId = pending.runId!;
          const recoveryStartedAt = Date.now();
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
                const current = useStore.getState();
                const localMessages = current.sessionId === sessionId ? current.messages
                  : loadMessagesForSession(sessionId, { preserveLoading: true });
                const localBlocks = localMessages.find((row) => row.id === pending.id)?.blocks;
                const blocks = Array.isArray(message?.blocks) ? message.blocks
                  : Array.isArray(result?.blocks) ? result.blocks : localBlocks;
                useStore.getState().updateMessageInSession(sessionId, pending.id, {
                  id: run.assistant_message_id || pending.id, content, isLoading: false,
                  timestamp: typeof run.created_at === 'number' && run.created_at > 0 ? run.created_at * 1000 : pending.timestamp,
                  runStatus: run.status, answerStatus: message?.answer_status || result?.answer_status,
                  ...(Array.isArray(blocks) ? { blocks: publicResearchBlocks(blocks) } : {}),
                  reviewRevision: message?.review_revision || result?.review_revision || pending.reviewRevision,
                  thinking: message?.thinking || result?.thinking,
                  evidence_pool: message?.evidence_pool || result?.evidence_pool,
                  priceLevels: message?.price_levels || result?.price_levels,
                  report: message?.report || result?.report || result?.blocked_report,
                  error: completed ? undefined : String(message?.error || content),
                  canRetry: !completed || message?.canRetry === true || result?.quality_blocked === true,
                }, { syncBackend: false });
                break;
              }
              const runStartedAt = typeof run.created_at === 'number' && run.created_at > 0 ? run.created_at * 1000 : recoveryStartedAt;
              useStore.getState().updateMessageInSession(sessionId, pending.id, {
                isLoading: true, runStatus: 'running', error: undefined, canRetry: false,
                timestamp: runStartedAt,
              }, { syncBackend: false });
              await new Promise<void>((resolve) => {
                const timer = setTimeout(() => { controller.signal.removeEventListener('abort', stop); resolve(); }, 1500);
                const stop = () => { clearTimeout(timer); resolve(); };
                controller.signal.addEventListener('abort', stop, { once: true });
              });
            }
          } catch {
            if (stillOwned()) useStore.getState().updateMessageInSession(sessionId, pending.id, {
              isLoading: false, error: zh.chat.savedAnswerInterrupted, canRetry: true,
              runStatus: 'interrupted',
            }, { syncBackend: false });
          }
          if (!stillOwned()) return;
        }
      } finally {
        const current = useStore.getState();
        if (current.authIdentity?.userId === owner && current.abortControllersBySession[sessionId] === controller) {
          current.setSessionLoading(sessionId, false);
          current.setSessionAbortController(sessionId, null);
          if (current.sessionId === sessionId) current.setStatus(null);
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
  return { WELCOME_MESSAGE, conversationSyncs, cancelConversationSync, createBackendConversation, flushConversationSync, deleteBackendConversation, loadConversationSummaries, upsertConversationSummary, loadMessagesForSession, getInitialMessages, needsBackendHistory, hydrateMessagesFromBackend, persistMessages, persistConversationSummaries, appendMessageForSession, patchMessageForSession, clearPersistedMessages, clearPersistedConversation };
};

export type ConversationServices = ReturnType<typeof createConversationServices>;

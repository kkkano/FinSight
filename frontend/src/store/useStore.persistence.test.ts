import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Message } from '../types';

vi.mock('../api/client', () => ({ apiClient: {
  createConversation: vi.fn().mockResolvedValue({ success: true }),
  getConversation: vi.fn().mockResolvedValue({ success: true }),
  deleteConversation: vi.fn().mockResolvedValue({ success: true }),
  getExecutionRun: vi.fn(),
} }));
vi.mock('../api/http', () => ({ buildAuthHeaders: vi.fn().mockResolvedValue({ Authorization: 'Bearer fixture-token' }) }));

const owner = 'persistence-fixture-owner';
const session = `public:${owner}:snapshot`;
let values: Map<string, string>;

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.setSystemTime(1000);
  values = new Map([['finsight-session-id', 'public:anonymous:snapshot']]);
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
    key: (index: number) => [...values.keys()][index] ?? null,
    get length() { return values.size; },
  };
  vi.stubGlobal('window', { localStorage: storage, addEventListener: vi.fn(), matchMedia: () => ({ matches: false }) });
  vi.stubGlobal('document', { documentElement: { classList: { toggle: vi.fn() } } });
});

afterEach(async () => {
  const { flushPersist } = await import('./persistScheduler');
  flushPersist();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('existing store persistence contract', () => {
  it('keeps every storage key and the exact local message projection', async () => {
    const { useStore } = await import('./useStore');
    const state = useStore.getState();
    state.setAuthIdentity({ userId: owner, email: null });
    state.setSessionId(session);
    state.setTheme('light');
    state.setColorConvention('cn');
    state.setLayoutMode('full');
    state.setChatStyle('flat');
    state.setEntryMode('authenticated');
    state.setTraceRawEnabled(true);
    state.setTraceViewMode('dev');
    state.setTraceRawShowRawJson(true);
    state.setWatchlistAutoConfirm(true);
    state.setShowProviderReasoning(true);
    const user: Message = { id: 'snapshot-user', role: 'user', content: '协议问题', timestamp: 1001 };
    const answer: Message = { id: 'snapshot-answer', role: 'assistant', content: '暂存正文', timestamp: 1002,
      isLoading: true, runId: 'snapshot-run', replyTo: user.id, thinking: [], evidence_pool: [], canRetry: false };
    state.addMessage(user);
    state.addMessage(answer);
    const patch = { content: '最终正文', isLoading: false, runStatus: 'completed', answerStatus: 'answered' };
    useStore.getState().updateMessage(answer.id, patch);
    await useStore.getState().flushConversationSync(session);

    expect([...values.keys()].sort()).toEqual([
      'finsight-chat-style', 'finsight-color-convention', 'finsight-conversations', 'finsight-entry-mode',
      'finsight-layout', `finsight-messages:${session}`, `finsight-research-preferences:${owner}`,
      'finsight-session-id', 'finsight-theme', 'finsight-trace-raw-enabled',
      'finsight-trace-raw-show-json', 'finsight-trace-view-mode',
    ].sort());
    expect(Object.fromEntries([...values].filter(([key]) => !key.startsWith('finsight-messages:') && key !== 'finsight-conversations'))).toEqual({
      'finsight-chat-style': 'flat', 'finsight-color-convention': 'cn', 'finsight-entry-mode': 'authenticated',
      'finsight-layout': 'full', [`finsight-research-preferences:${owner}`]: '{"watchlistAutoConfirm":true,"showProviderReasoning":true}',
      'finsight-session-id': session, 'finsight-theme': 'light', 'finsight-trace-raw-enabled': 'true',
      'finsight-trace-raw-show-json': 'true', 'finsight-trace-view-mode': 'dev',
    });
    const persisted = JSON.parse(values.get(`finsight-messages:${session}`)!);
    expect(persisted.find((message: Message) => message.id === answer.id)).toEqual({ ...answer, ...patch });
    expect(persisted.find((message: Message) => message.id === user.id)).toEqual(user);
    const summary = JSON.parse(values.get('finsight-conversations')!).find((row: { sessionId: string }) => row.sessionId === session);
    expect(Object.keys(summary).sort()).toEqual(['sessionId', 'title', 'tickers', 'runStatus', 'answerStatus',
      'lastMessagePreview', 'messageCount', 'createdAt', 'updatedAt'].sort());
  });

  it('keeps per-owner research preferences and excludes model credentials', async () => {
    const { useStore, normalizePersistedEntryMode } = await import('./useStore');
    const { useModelSelectionStore } = await import('./modelSelection');
    useStore.getState().setAuthIdentity({ userId: owner, email: null });
    useStore.getState().setWatchlistAutoConfirm(true);
    useStore.getState().setShowProviderReasoning(true);
    useModelSelectionStore.getState().applySelection({ source: 'custom', base_url: 'https://example.invalid/v1',
      api_key: 'fixture-private-selection-key', model: 'fixture-model', context_acknowledged: true }, {
      provider: 'fixture', label: 'Fixture', icon_url: null, effort_options: [], default_effort: null, docs_url: null,
    });
    expect([...values.values()].join('')).not.toContain('fixture-private-selection-key');
    expect(normalizePersistedEntryMode('authenticated')).toBe('pending');
    useStore.getState().setAuthIdentity({ userId: 'other-fixture-owner', email: null });
    expect(useStore.getState().watchlistAutoConfirm).toBe(false);
    expect(useStore.getState().showProviderReasoning).toBe(false);
    useStore.getState().setAuthIdentity({ userId: owner, email: null });
    expect(useStore.getState().watchlistAutoConfirm).toBe(true);
    expect(useStore.getState().showProviderReasoning).toBe(true);
  });
});

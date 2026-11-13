import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readResearchPreferences, writeResearchPreferences } from './researchPreferences';
import { useStore } from './useStore';
import { apiClient } from '../api/client';

describe('account-scoped research preferences', () => {
  const storage = new Map<string, string>();
  beforeEach(() => {
    vi.spyOn(apiClient, 'createConversation').mockResolvedValue({success:true,session_id:'public:preferences-test:default'});
    vi.spyOn(apiClient, 'getConversation').mockResolvedValue({success:true,session_id:'public:preferences-test:default'});
    storage.clear();
    vi.stubGlobal('window', { localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value); },
      removeItem: (key: string) => { storage.delete(key); },
    } });
    useStore.getState().setAuthIdentity(null);
  });
  afterEach(() => { useStore.getState().setAuthIdentity(null); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
  it('defaults both preferences off and ignores non-boolean persisted values', () => {
    expect(readResearchPreferences('a')).toEqual({ watchlistAutoConfirm: false, showProviderReasoning: false });
    storage.set('finsight-research-preferences:a', '{"watchlistAutoConfirm":"true","showProviderReasoning":1}');
    expect(readResearchPreferences('a')).toEqual({ watchlistAutoConfirm: false, showProviderReasoning: false });
    writeResearchPreferences(null, { watchlistAutoConfirm: true, showProviderReasoning: true });
    expect(storage.size).toBe(1);
  });
  it('switches and restores accounts without inheriting another account authorization', () => {
    const state = useStore.getState();
    state.setAuthIdentity({ userId: 'a', email: null });
    state.setWatchlistAutoConfirm(true); state.setShowProviderReasoning(true);
    expect(readResearchPreferences('a')).toEqual({ watchlistAutoConfirm: true, showProviderReasoning: true });
    state.setAuthIdentity({ userId: 'b', email: null });
    expect(useStore.getState().watchlistAutoConfirm).toBe(false);
    expect(useStore.getState().showProviderReasoning).toBe(false);
    state.setAuthIdentity({ userId: 'a', email: null });
    expect(useStore.getState().watchlistAutoConfirm).toBe(true);
    state.setAuthIdentity(null); state.setWatchlistAutoConfirm(true); state.setShowProviderReasoning(true);
    expect(useStore.getState().watchlistAutoConfirm).toBe(false);
    expect(useStore.getState().showProviderReasoning).toBe(false);
  });
});

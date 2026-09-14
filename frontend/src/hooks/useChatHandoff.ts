import { useCallback } from 'react';
import { useNavigate, type NavigateFunction } from 'react-router-dom';

import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import type { ChatHandoff } from '../types/chatHandoff';

const SYMBOL_PATTERN = /^(?=.{1,32}$)(?:\^[A-Z0-9][A-Z0-9.-]*|[A-Z0-9][A-Z0-9.-]*(?:=[A-Z])?)$/;

function hasControlCharacter(value: string): boolean {
  for (const character of value) {
    const code = character.charCodeAt(0);
    if (code <= 0x1f || code === 0x7f) return true;
  }
  return false;
}

function normalizeSymbol(value: string | undefined): string | undefined {
  const normalized = String(value ?? '').trim().toUpperCase();
  return normalized && SYMBOL_PATTERN.test(normalized) ? normalized : undefined;
}

function normalizeSourceTab(value: string | undefined): string | undefined {
  const normalized = String(value ?? '').trim();
  return normalized && normalized.length <= 64 && !hasControlCharacter(normalized)
    ? normalized
    : undefined;
}

export function performChatHandoff(handoff: ChatHandoff, navigate: NavigateFunction): boolean {
  const draft = String(handoff.draft ?? '').trim();
  if (!draft) return false;

  const chatStore = useStore.getState();
  const dashboardStore = useDashboardStore.getState();
  const sessionId = chatStore.sessionId;
  if (!sessionId) return false;

  const providedSymbol = handoff.activeSymbol === undefined
    ? undefined
    : normalizeSymbol(handoff.activeSymbol);
  if (providedSymbol && providedSymbol !== dashboardStore.activeAsset?.symbol) {
    dashboardStore.setActiveAsset({
      symbol: providedSymbol,
      display_name: providedSymbol,
      type: dashboardStore.activeAsset?.type ?? 'equity',
    });
  }
  if (handoff.selections !== undefined) {
    useDashboardStore.getState().setSelections(handoff.selections);
  }

  chatStore.setDraft(draft);
  chatStore.setPendingChatHandoffContext(sessionId, {
    sessionId,
    sourceView: handoff.sourceView,
    sourceTab: normalizeSourceTab(handoff.sourceTab),
  });

  const activeSymbol = providedSymbol
    ?? normalizeSymbol(useDashboardStore.getState().activeAsset?.symbol);
  const params = new URLSearchParams({ prompt: draft });
  if (activeSymbol) params.set('context_symbol', activeSymbol);
  navigate({ pathname: '/chat', search: `?${params.toString()}` });
  return true;
}

export function useChatHandoff(): (handoff: ChatHandoff) => boolean {
  const navigate = useNavigate();
  return useCallback(
    (handoff: ChatHandoff) => performChatHandoff(handoff, navigate),
    [navigate],
  );
}

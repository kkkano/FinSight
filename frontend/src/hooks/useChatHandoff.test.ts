import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { NavigateFunction } from 'react-router-dom';

import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import { performChatHandoff } from './useChatHandoff';

describe('performChatHandoff', () => {
  beforeEach(() => {
    useStore.getState().setSessionId('public:test-user:handoff');
    useStore.setState({ draft: '', pendingChatHandoffContextBySession: {} });
    useDashboardStore.setState({ activeAsset: null, activeSelections: [] });
  });

  it('overwrites the current draft and carries selections outside the URL', () => {
    const navigateMock = vi.fn();
    const navigate = navigateMock as unknown as NavigateFunction;
    const selection = {
      type: 'news' as const,
      id: 'news-1',
      title: 'Apple launches a product',
      snippet: 'private selection body',
    };

    expect(performChatHandoff({
      draft: '  请分析这条新闻  ',
      activeSymbol: ' aapl ',
      selections: [selection],
      sourceView: 'dashboard',
      sourceTab: ' news ',
    }, navigate)).toBe(true);

    expect(useStore.getState().draft).toBe('请分析这条新闻');
    expect(useDashboardStore.getState().activeSelections).toEqual([selection]);
    expect(useStore.getState().pendingChatHandoffContextBySession['public:test-user:handoff']).toEqual({
      sessionId: 'public:test-user:handoff',
      sourceView: 'dashboard',
      sourceTab: 'news',
    });
    const destination = navigateMock.mock.calls[0]?.[0] as { pathname: string; search: string };
    expect(destination.pathname).toBe('/chat');
    expect(destination.search).toContain('prompt=');
    expect(destination.search).toContain('context_symbol=AAPL');
    expect(destination.search).not.toContain('private');
    expect(destination.search).not.toContain('source');
  });

  it('rejects an empty draft without changing state or navigating', () => {
    const navigateMock = vi.fn();
    const navigate = navigateMock as unknown as NavigateFunction;
    expect(performChatHandoff({ draft: '  ', sourceView: 'dashboard' }, navigate)).toBe(false);
    expect(navigateMock).not.toHaveBeenCalled();
    expect(useStore.getState().pendingChatHandoffContextBySession).toEqual({});
  });
});

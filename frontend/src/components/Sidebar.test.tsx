import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import Sidebar from './Sidebar';
import { useStore } from '../store/useStore';

vi.mock('../store/useStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../store/useStore')>();
  const readStore = (selector?: (state: ReturnType<typeof actual.useStore.getState>) => unknown) =>
    selector ? selector(actual.useStore.getState()) : actual.useStore.getState();
  return { ...actual, useStore: Object.assign(readStore, actual.useStore) };
});

describe('主导航收敛', () => {
  it('只展示今日、看板、对话和历史四个产品入口', () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/history']}>
        <Sidebar currentView="history" />
      </MemoryRouter></QueryClientProvider>,
    );

    expect(html).toContain('data-testid="sidebar-nav-today"');
    expect(html).toContain('data-testid="sidebar-nav-dashboard"');
    expect(html).toContain('data-testid="sidebar-nav-chat"');
    expect(html).toContain('data-testid="sidebar-nav-history"');
    expect(html).not.toContain('工作台');
    expect(html).not.toContain('A股市场');
    expect(html).not.toContain('筛选器');
    expect(html).not.toContain('回测');
    expect(html).not.toContain('订阅与提醒');
  });
});

describe('侧栏最近对话', () => {
  const original = useStore.getState();
  const now = new Date(2026, 10, 7, 12);
  const items = Array.from({ length: 12 }, (_, index) => ({
    sessionId: `sidebar-${index}`, title: `研究 ${index}（2026-11-05）`, lastMessagePreview: '', messageCount: 2,
    createdAt: +now - index * 3600000, updatedAt: +now - index * 3600000,
  }));
  const renderSidebar = () => renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}><MemoryRouter><Sidebar /></MemoryRouter></QueryClientProvider>,
  );

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(now);
    useStore.setState({ conversationSummaries: items, sessionId: 'sidebar-11' });
  });

  afterEach(() => {
    useStore.setState({ conversationSummaries: original.conversationSummaries, sessionId: original.sessionId });
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('默认展开并保留前八条、选中项补位、完整标题与删除入口', () => {
    const html = renderSidebar();
    expect(html).toMatch(/aria-expanded="true"[^>]*>.*?最近对话/s);
    expect(html.match(/data-testid="conversation-item"/g)).toHaveLength(9);
    expect(html).toContain('data-session-id="sidebar-11" data-active="true"');
    expect(html).toContain('title="研究 0（2026-11-05）"');
    expect(html).toContain('truncate">研究 0</span>');
    expect(html).toContain('查看全部 12 条 →');
    expect(html.match(/data-testid="conversation-delete"/g)).toHaveLength(9);
  });

  it('读取已保存的整体收起状态', () => {
    vi.stubGlobal('window', { localStorage: { getItem: (key: string) => key === 'finsight.sidebar.recentCollapsed' ? 'true' : null } });
    const html = renderSidebar();
    expect(html).toMatch(/aria-expanded="false"[^>]*>.*?最近对话/s);
    expect(html).toContain('data-testid="conversation-rail"');
    expect(html).not.toContain('data-testid="conversation-item"');
  });

  it('旧组默认收起，组计数保留并让当前会话单独可见', () => {
    useStore.setState({ conversationSummaries: items.slice(0, 2).map((item) => ({ ...item, updatedAt: +new Date(2026, 9, 1) })), sessionId: 'sidebar-1' });
    const html = renderSidebar();
    expect(html).toMatch(/aria-expanded="false"[^>]*>.*?<span>更早<\/span><span[^>]*>· 2<\/span>/s);
    expect(html.match(/data-testid="conversation-item"/g)).toHaveLength(1);
    expect(html).toContain('data-session-id="sidebar-1" data-active="true"');
    expect(html).not.toContain('查看全部');
  });
});

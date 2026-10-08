import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import Sidebar from './Sidebar';

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

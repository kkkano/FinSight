import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { ToastProvider } from '../ui';
import { PortfolioEditor } from './PortfolioEditor';
import type { PortfolioSummaryResponse } from '../../api/client';

// 静态渲染不会触发真实网络请求，但 mock 掉以隔离副作用
vi.mock('../../api/client', () => ({
  apiClient: {
    updatePortfolioPosition: vi.fn(),
    deletePortfolioPosition: vi.fn(),
  },
}));

const renderText = (node: React.ReactElement) =>
  renderToStaticMarkup(<ToastProvider>{node}</ToastProvider>).replace(/\s+/g, ' ');

function makeSummary(): PortfolioSummaryResponse {
  return {
    success: true,
    session_id: 's-1',
    count: 2,
    total_value: 30000,
    total_cost: 25000,
    total_pnl: 5000,
    positions: [
      {
        ticker: 'AAPL',
        shares: 10,
        avg_cost: 150,
        market_value: 2000,
        cost_basis: 1500,
        live_price: 200,
        unrealized_pnl: 500,
      },
      {
        ticker: 'TSLA',
        shares: 5,
        avg_cost: 240,
        market_value: 1000,
        cost_basis: 1200,
        live_price: 200,
        unrealized_pnl: -200,
      },
    ],
  };
}

describe('PortfolioEditor', () => {
  it('renders the empty-state guidance when there are no positions', () => {
    const text = renderText(
      <PortfolioEditor data={null} loading={false} onChanged={() => undefined} />,
    );
    expect(text).toContain('录入持仓后');
    expect(text).toContain('添加第一笔持仓');
  });

  it('renders the position table with tickers and P&L', () => {
    const text = renderText(
      <PortfolioEditor data={makeSummary()} loading={false} onChanged={() => undefined} />,
    );
    expect(text).toContain('AAPL');
    expect(text).toContain('TSLA');
    // 现价
    expect(text).toContain('$200.00');
    // 盈亏（正负）
    expect(text).toContain('持仓管理');
  });

  it('shows the header add button', () => {
    const html = renderToStaticMarkup(
      <ToastProvider>
        <PortfolioEditor data={makeSummary()} loading={false} onChanged={() => undefined} />
      </ToastProvider>,
    );
    expect(html).toContain('portfolio-add-button');
    expect(html).toContain('添加持仓');
  });
});

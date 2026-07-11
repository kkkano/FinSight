import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../components/screener/ScreenerResultPanel', () => ({
  ScreenerResultPanel: () => <div data-testid="screener-panel">screener-panel</div>,
}));

vi.mock('../components/backtest/BacktestPanel', () => ({
  BacktestPanel: () => <div data-testid="backtest-panel">backtest-panel</div>,
}));

import { BacktestPage } from './BacktestPage';
import { ScreenerPage } from './ScreenerPage';

const render = (node: React.ReactElement) =>
  renderToStaticMarkup(<MemoryRouter>{node}</MemoryRouter>);

describe('一级功能页面', () => {
  it('智能选股页面复用现有 screener 面板', () => {
    const html = render(<ScreenerPage />);
    expect(html).toContain('智能选股');
    expect(html).toContain('screener-panel');
    expect(html).toContain('href="/workbench"');
  });

  it('策略回测页面复用现有 backtest 面板', () => {
    const html = render(<BacktestPage />);
    expect(html).toContain('策略回测');
    expect(html).toContain('backtest-panel');
    expect(html).toContain('href="/workbench"');
  });
});

import React from 'react';
import { Link } from 'react-router-dom';

import { BacktestPanel } from '../backtest/BacktestPanel';
import { CNMarketPanel } from '../cn-market/CNMarketPanel';
import { ScreenerResultPanel } from '../screener/ScreenerResultPanel';

export const Phase24PanelsPage: React.FC = () => {
  return (
    <main className="min-h-screen bg-fin-bg px-4 py-6 md:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-fin-text">Phase 2-4 功能面板</h1>
            <p className="text-sm text-fin-muted">选股、A股市场扩展、策略回测</p>
          </div>
          <Link to="/workbench" className="rounded-md border border-fin-border px-3 py-2 text-sm text-fin-text hover:bg-fin-bg-secondary">
            返回 Workbench
          </Link>
        </header>

        <section className="grid gap-6">
          <ScreenerResultPanel />
          <CNMarketPanel />
          <BacktestPanel />
        </section>
      </div>
    </main>
  );
};

export default Phase24PanelsPage;

import React from 'react';
import { Link } from 'react-router-dom';

import { BacktestPanel } from '../components/backtest/BacktestPanel';

export const BacktestPage: React.FC = () => (
  <main id="main-content" className="min-h-screen bg-fin-bg px-4 py-6 md:px-8">
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fin-text">策略回测</h1>
          <p className="text-sm text-fin-muted">用历史行情验证策略表现与风险</p>
        </div>
        <Link
          to="/workbench"
          className="rounded-md border border-fin-border px-3 py-2 text-sm text-fin-text hover:bg-fin-bg-secondary"
        >
          返回工作台
        </Link>
      </header>
      <BacktestPanel />
    </div>
  </main>
);

export default BacktestPage;

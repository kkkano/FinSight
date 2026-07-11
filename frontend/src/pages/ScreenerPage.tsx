import React from 'react';
import { Link } from 'react-router-dom';

import { ScreenerResultPanel } from '../components/screener/ScreenerResultPanel';

export const ScreenerPage: React.FC = () => (
  <main id="main-content" className="min-h-screen bg-fin-bg px-4 py-6 md:px-8">
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-fin-text">智能选股</h1>
          <p className="text-sm text-fin-muted">按市场、估值与技术条件筛选候选标的</p>
        </div>
        <Link
          to="/workbench"
          className="rounded-md border border-fin-border px-3 py-2 text-sm text-fin-text hover:bg-fin-bg-secondary"
        >
          返回工作台
        </Link>
      </header>
      <ScreenerResultPanel />
    </div>
  </main>
);

export default ScreenerPage;

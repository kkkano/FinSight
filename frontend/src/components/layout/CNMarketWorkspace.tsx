/**
 * CNMarketWorkspace - A股市场主导航工作区。
 *
 * P2-6：把原先藏在 /phase-labs 实验页的 CNMarketPanel（资金流/北向/涨跌停/
 * 龙虎榜/概念板块）提升为主导航入口 /cn-market，直接复用现有组件，不复制代码。
 */
import { TrendingUp } from 'lucide-react';

import { CNMarketPanel } from '../cn-market/CNMarketPanel';

export function CNMarketWorkspace() {
  return (
    <div className="h-full flex-1 min-w-0 min-h-0 overflow-y-auto p-5 max-lg:p-3">
      <div className="mx-auto max-w-5xl space-y-4">
        <header className="flex items-center gap-2">
          <TrendingUp size={20} className="text-fin-primary" />
          <div>
            <h1 className="text-lg font-semibold text-fin-text">A 股市场</h1>
            <p className="text-xs text-fin-muted">资金流向 · 北向资金 · 涨跌停 · 龙虎榜 · 概念板块</p>
          </div>
        </header>

        <CNMarketPanel />
      </div>
    </div>
  );
}

export default CNMarketWorkspace;

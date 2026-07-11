import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { BacktestPanel } from './BacktestPanel';

describe('BacktestPanel 报告预填', () => {
  it('展示报告来源、日期输入与 buy-and-hold 策略', () => {
    const html = renderToStaticMarkup(
      <BacktestPanel
        initialConfig={{
          tickers: ['AAPL', 'MSFT'],
          strategy: 'buy_and_hold',
          start: '2025-07-11',
          end: '2026-07-11',
          rationale: '由报告《Apple research》生成：主标的 AAPL, MSFT，观点 BUY',
        }}
      />,
    );

    expect(html).toContain('报告预填');
    expect(html).toContain('Apple research');
    expect(html).toContain('当前回测引擎为单标的');
    expect(html).toContain('Buy &amp; Hold 买入并持有');
    expect(html).toContain('开始日期');
    expect(html).toContain('结束日期');
  });
});

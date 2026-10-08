import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import type { FinancialStatement } from '../../../../types/dashboard';
import { IncomeTable } from './IncomeTable';
import { ProfitabilityChart } from './ProfitabilityChart';
import { BalanceSheetSummary } from './BalanceSheetSummary';

vi.mock('echarts-for-react', () => ({ default: ({ option }: { option: unknown }) => <pre>{JSON.stringify(option)}</pre> }));
vi.mock('../../../../hooks/useChartTheme', () => ({ useChartTheme: () => ({}) }));

const render = (node: ReactNode) => renderToStaticMarkup(
  <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>,
);

const annual: FinancialStatement = {
  periods: ['2025-12-31', '2024-12-31'], period_ends: ['2025-12-31', '2024-12-31'],
  currency: 'CNY', frequency: 'annual', revenue: [200, 100], gross_profit: [80, 40],
  operating_income: [40, 20], net_income: [null, 20], eps: [1, 0.5],
  total_assets: [500, null], total_liabilities: [null, 200], operating_cash_flow: [], free_cash_flow: [],
  yoy: { revenue: [1, null] }, gross_margin: [40, 40], net_margin: [null, 20],
  balance_summary: { period: '2025-12-31', total_assets: 500, total_liabilities: null, equity: null, de_ratio: null },
};

describe('financial source contract in rendered views', () => {
  it('keeps annual dates, report currency and server period comparisons', () => {
    const html = render(<IncomeTable financials={annual} />);
    expect(html).toContain('年度');
    expect(html).toContain('2025-12-31');
    expect(html).not.toContain('Q4');
    expect(html).not.toContain('$');
    expect(html).toContain('text-fin-success');
  });

  it('keeps missing profit and margin as null in the actual chart series', () => {
    const html = render(<ProfitabilityChart financials={annual} />);
    expect(html).toContain('&quot;data&quot;:[20,null]');
    expect(html).toContain('&quot;data&quot;:[100,200]');
  });

  it('does not derive equity from unmatched raw asset and liability periods', () => {
    const html = render(<BalanceSheetSummary financials={annual} />);
    expect(html).not.toContain('300');
    expect(html).toContain('--');
    expect(html).toContain('2025-12-31');
  });
});

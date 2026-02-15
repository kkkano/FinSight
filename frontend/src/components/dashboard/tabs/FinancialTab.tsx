/**
 * FinancialTab - Container component for the financial dashboard panel.
 *
 * Renders financial sub-components:
 * Row 1: IncomeTable (full width)
 * Row 2: ProfitabilityChart + ValuationGrid
 * Row 3: BalanceSheetSummary
 */
import { useDashboardStore } from '../../../store/dashboardStore';
import { IncomeTable } from './financial/IncomeTable';
import { ProfitabilityChart } from './financial/ProfitabilityChart';
import { ValuationGrid } from './financial/ValuationGrid';
import { BalanceSheetSummary } from './financial/BalanceSheetSummary';

// --- Component ---

export function FinancialTab() {
  const dashboardData = useDashboardStore((s) => s.dashboardData);

  const financials = dashboardData?.financials;
  const valuation = dashboardData?.valuation;

  return (
    <div className="flex flex-col gap-4">
      {/* Row 1: Income table full width */}
      <IncomeTable financials={financials} />

      {/* Row 2: Profitability + Valuation side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ProfitabilityChart financials={financials} />
        <ValuationGrid valuation={valuation} />
      </div>

      {/* Row 3: Balance sheet summary */}
      <BalanceSheetSummary financials={financials} />
    </div>
  );
}

export default FinancialTab;

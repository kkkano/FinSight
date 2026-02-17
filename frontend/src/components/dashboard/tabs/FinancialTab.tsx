/**
 * FinancialTab - Container component for the financial dashboard panel.
 *
 * Renders financial sub-components:
 * AI Insight Card (full width, when available)
 * Row 1: IncomeTable (full width)
 * Row 2: ProfitabilityChart + ValuationGrid
 * Row 3: BalanceSheetSummary
 */
import { useDashboardStore } from '../../../store/dashboardStore';
import { IncomeTable } from './financial/IncomeTable';
import { ProfitabilityChart } from './financial/ProfitabilityChart';
import { ValuationGrid } from './financial/ValuationGrid';
import { BalanceSheetSummary } from './financial/BalanceSheetSummary';
import { AiInsightCard } from './shared/AiInsightCard';

// --- Component ---

export function FinancialTab() {
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);

  const financials = dashboardData?.financials;
  const valuation = dashboardData?.valuation;
  const financialInsight = insightsData?.financial ?? null;

  return (
    <div className="flex flex-col gap-4">
      {/* AI Financial Analysis Card */}
      <AiInsightCard
        tab="financial"
        insight={financialInsight}
        loading={insightsLoading}
        error={insightsError}
        stale={insightsStale}
      />

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

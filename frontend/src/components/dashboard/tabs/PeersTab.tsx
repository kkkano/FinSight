/**
 * PeersTab - Container component for the Peers tab panel.
 *
 * Combines AiInsightCard (from Digest), PeerScoreGrid, PeerComparisonTable,
 * ValuationBarChart, RevenueGrowthChart, and AiPeerSummary (report fallback)
 * using peer data from dashboardStore and report data from useLatestReport.
 */
import { useDashboardStore } from '../../../store/dashboardStore.ts';
import { useLatestReport } from '../../../hooks/useLatestReport.ts';
import { PeerScoreGrid } from './peers/PeerScoreGrid.tsx';
import { PeerComparisonTable } from './peers/PeerComparisonTable.tsx';
import { ValuationBarChart } from './peers/ValuationBarChart.tsx';
import { RevenueGrowthChart } from './peers/RevenueGrowthChart.tsx';
import { AiPeerSummary } from './peers/AiPeerSummary.tsx';
import { AiInsightCard } from './shared/AiInsightCard';

export function PeersTab() {
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);

  const ticker = activeAsset?.symbol ?? null;
  const { data: reportData, loading: reportLoading } = useLatestReport(ticker, {
    sourceType: 'dashboard',
    fallbackToAnySource: false,
  });

  const peerData = dashboardData?.peers ?? null;
  const subjectSymbol = peerData?.subject_symbol ?? ticker ?? '';
  const peers = peerData?.peers ?? [];
  const peersInsight = insightsData?.peers ?? null;

  if (!dashboardData) {
    return (
      <div className="flex items-center justify-center h-64 text-fin-muted text-sm">
        暂无数据，请先选择资产
      </div>
    );
  }

  if (peers.length === 0 && !peerData) {
    return (
      <div className="space-y-4">
        <AiInsightCard
          tab="peers"
          insight={peersInsight}
          loading={insightsLoading}
          error={insightsError}
          stale={insightsStale}
        />
        {!peersInsight && !insightsLoading && (
          <AiPeerSummary reportData={reportData} loading={reportLoading} />
        )}
        <div className="flex items-center justify-center h-48 text-fin-muted text-sm">
          {dashboardData.peers_fallback_reason
            ? `同行数据不可用: ${dashboardData.peers_fallback_reason}`
            : '暂无同行对比数据'}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* AI Peers Insight Card — replaces AiPeerSummary when insights available */}
      <AiInsightCard
        tab="peers"
        insight={peersInsight}
        loading={insightsLoading}
        error={insightsError}
        stale={insightsStale}
      />
      {/* Fallback: report-based peer summary (hidden when insight is present) */}
      {!peersInsight && !insightsLoading && (
        <AiPeerSummary reportData={reportData} loading={reportLoading} />
      )}

      {/* Score grid (top 6) */}
      <PeerScoreGrid peers={peers} subjectSymbol={subjectSymbol} />

      {/* Valuation bar chart */}
      <ValuationBarChart peers={peers} subjectSymbol={subjectSymbol} />

      {/* Revenue growth chart */}
      <RevenueGrowthChart peers={peers} subjectSymbol={subjectSymbol} />

      {/* Full comparison table */}
      <div className="bg-fin-card border border-fin-border rounded-lg p-4">
        <h4 className="text-sm font-semibold text-fin-text mb-3">详细对比</h4>
        <PeerComparisonTable peers={peers} subjectSymbol={subjectSymbol} />
      </div>
    </div>
  );
}

export default PeersTab;

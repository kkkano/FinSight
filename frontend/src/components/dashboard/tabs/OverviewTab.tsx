/**
 * OverviewTab - Container component for the overview dashboard panel.
 *
 * Layout strategy:
 * - Top: AI overview card (full width)
 * - Bottom: 3-column stacked layout (masonry-like) to avoid row-height whitespace
 */
import { useDashboardStore } from '../../../store/dashboardStore';
import { useLatestReport } from '../../../hooks/useLatestReport';
import type { SelectionItem, TechnicalData, NewsItem, PeerMetrics } from '../../../types/dashboard';
import { ScoreRing } from './overview/ScoreRing';
import { AnalystRatingCard } from './overview/AnalystRatingCard';
import { DimensionRadar } from './overview/DimensionRadar';
import { KeyInsightsCard } from './overview/KeyInsightsCard';
import { RiskMetricsCard } from './overview/RiskMetricsCard';
import { HighlightsCard } from './overview/HighlightsCard';
import { FearGreedGauge } from './overview/FearGreedGauge';
import { AgentStatusOverview } from './overview/AgentStatusOverview';
import { AiInsightCard } from './shared/AiInsightCard';
import { AnalystTargetCard } from './financial/AnalystTargetCard';
import { asRecord } from '../../../utils/record';

interface ActionSuggestion {
  action: string;
  rationale: string;
  entryRange: string | null;
  takeProfit: string | null;
  stopLoss: string | null;
}

function normalizeRecommendationText(reportData: ReturnType<typeof useLatestReport>['data']): string {
  const report = asRecord(reportData?.report);
  return String(report?.recommendation ?? report?.sentiment ?? '').trim().toLowerCase();
}

function getRecommendationAction(reportData: ReturnType<typeof useLatestReport>['data'], score: number | null | undefined): string {
  const recText = normalizeRecommendationText(reportData);
  if (/(strong\s*)?buy|bull|positive|增持|买入|强烈买入/.test(recText)) return '买入';
  if (/(strong\s*)?sell|bear|negative|减持|卖出|强烈卖出/.test(recText)) return '卖出';
  if (/hold|neutral|中性|持有|观望/.test(recText)) return '持有';

  if (score == null || !Number.isFinite(score)) return '持有';
  if (score >= 8) return '强烈买入';
  if (score >= 6) return '买入';
  if (score >= 4) return '持有';
  if (score >= 3) return '观望';
  return '减仓';
}

function pickSupportResistance(technicals?: TechnicalData | null, currentPrice?: number | null): {
  entryRange: string | null;
  takeProfit: string | null;
  stopLoss: string | null;
} {
  const support = [...(technicals?.support_levels ?? [])]
    .filter((level): level is number => Number.isFinite(level))
    .sort((left, right) => left - right);
  const resistance = [...(technicals?.resistance_levels ?? [])]
    .filter((level): level is number => Number.isFinite(level))
    .sort((left, right) => left - right);

  const upperSupport = support.filter((level) => currentPrice == null || level <= currentPrice).slice(-2);
  const entryCandidate = upperSupport.length >= 2 ? upperSupport : support.slice(0, 2);
  const entryRange = entryCandidate.length === 2
    ? `$${entryCandidate[0].toFixed(2)} - $${entryCandidate[1].toFixed(2)}`
    : entryCandidate.length === 1
      ? `$${entryCandidate[0].toFixed(2)}`
      : null;

  const nextResistance = resistance.find((level) => currentPrice == null || level >= currentPrice) ?? resistance.at(-1);
  const takeProfit = nextResistance != null ? `$${nextResistance.toFixed(2)}` : null;

  const stopBase = entryCandidate[0] ?? null;
  const stopLoss = stopBase != null ? `$${(stopBase * 0.97).toFixed(2)}` : null;
  return { entryRange, takeProfit, stopLoss };
}

function buildActionSuggestion(
  reportData: ReturnType<typeof useLatestReport>['data'],
  score: number | null | undefined,
  technicals?: TechnicalData | null,
): ActionSuggestion {
  const action = getRecommendationAction(reportData, score);
  const currentPrice = technicals?.close ?? null;
  const { entryRange, takeProfit, stopLoss } = pickSupportResistance(technicals, currentPrice);

  const rationale = action === '强烈买入' || action === '买入'
    ? '当前评分偏多，建议分批布局并控制仓位。'
    : action === '卖出' || action === '减仓'
      ? '当前信号偏弱，优先控制回撤风险。'
      : score == null || !Number.isFinite(score)
        ? '运行综合分析后可获得更准确的建议。'
        : '当前信号分歧较大，建议持有观望等待确认。';

  return { action, rationale, entryRange, takeProfit, stopLoss };
}

// --- NewsHighlightCard ---

function impactDot(level?: string) {
  if (level === 'high')   return 'bg-fin-danger';
  if (level === 'medium') return 'bg-fin-warning';
  return 'bg-fin-muted/50';
}

function timeAgo(ts?: string): string {
  if (!ts) return '';
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 3600)  return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${Math.floor(diff / 86400)}天前`;
}

function NewsHighlightCard({ news }: { news: NewsItem[] }) {
  const items = news.slice(0, 4);
  if (items.length === 0) return null;
  return (
    <div className="bg-fin-card rounded-xl border border-fin-border p-4">
      <div className="text-xs font-medium text-fin-muted mb-2.5">近期新闻</div>
      <ul className="space-y-2">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2">
            <span className={`mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full ${impactDot(item.impact_level)}`} />
            <div className="min-w-0">
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-fin-text/85 hover:text-fin-primary line-clamp-2 leading-relaxed transition-colors"
              >
                {item.title}
              </a>
              <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-fin-muted">
                {item.source && <span>{item.source}</span>}
                {item.source && item.ts && <span>·</span>}
                {item.ts && <span>{timeAgo(item.ts)}</span>}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- PeerSnapshotCard ---

function fmtPE(v?: number | null) {
  if (v == null || !Number.isFinite(v)) return '-';
  return v.toFixed(1);
}

function fmtMktCap(v?: number | null) {
  if (v == null || !Number.isFinite(v)) return '-';
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9)  return `$${(v / 1e9).toFixed(1)}B`;
  return `$${(v / 1e6).toFixed(0)}M`;
}

function PeerSnapshotCard({ peers, subjectSymbol }: { peers: PeerMetrics[]; subjectSymbol?: string }) {
  const items = peers.slice(0, 4);
  if (items.length === 0) return null;
  return (
    <div className="bg-fin-card rounded-xl border border-fin-border p-4">
      <div className="text-xs font-medium text-fin-muted mb-2.5">同行对比</div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-fin-muted border-b border-fin-border/50">
            <th className="pb-1.5 text-left font-medium">代码</th>
            <th className="pb-1.5 text-right font-medium">市盈率</th>
            <th className="pb-1.5 text-right font-medium">市值</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-fin-border/20">
          {items.map((p) => (
            <tr key={p.symbol} className={p.symbol === subjectSymbol ? 'text-fin-primary' : ''}>
              <td className="py-1.5 font-medium truncate max-w-[70px]" title={p.name}>
                {p.symbol}
              </td>
              <td className="py-1.5 text-right text-fin-text/80">{fmtPE(p.trailing_pe ?? p.forward_pe)}</td>
              <td className="py-1.5 text-right text-fin-text/80">{fmtMktCap(p.market_cap)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Component ---

export function OverviewTab() {
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const insightsData = useDashboardStore((s) => s.insightsData);
  const insightsLoading = useDashboardStore((s) => s.insightsLoading);
  const insightsError = useDashboardStore((s) => s.insightsError);
  const insightsStale = useDashboardStore((s) => s.insightsStale);
  const setActiveSelection = useDashboardStore((s) => s.setActiveSelection);
  const insightsRefetch = useDashboardStore((s) => s.insightsRefetch);

  const handleAskAbout = (selection: SelectionItem) => {
    setActiveSelection(selection);
  };

  const { data: reportData } = useLatestReport(activeAsset?.symbol, {
    sourceType: 'dashboard',
    fallbackToAnySource: false,
    preferredSourceTrigger: 'dashboard_deep_search',
  });

  const valuation = dashboardData?.valuation;
  const technicals = dashboardData?.technicals;
  const news = dashboardData?.news?.market;
  const analystTargets = dashboardData?.analyst_targets;
  const recommendations = dashboardData?.recommendations;
  const peerItems = dashboardData?.peers?.peers ?? [];
  const overviewInsight = insightsData?.overview ?? null;
  const actionSuggestion = buildActionSuggestion(reportData, overviewInsight?.score, technicals);

  return (
    <div className="space-y-4">
      {/* AI Overview Card (full width) */}
      <AiInsightCard
        tab="overview"
        insight={overviewInsight}
        loading={insightsLoading}
        error={insightsError}
        stale={insightsStale}
        actionSuggestion={actionSuggestion}
        onAskAbout={handleAskAbout}
        onRefresh={insightsRefetch ?? undefined}
      />

      {/* Unified stacked columns (reduce empty white blocks caused by row-based grid) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 items-start">
        <div className="space-y-4">
          <ScoreRing valuation={valuation} technicals={technicals} reportData={reportData} insightScore={overviewInsight?.score} />
          <FearGreedGauge reportData={reportData} macroSnapshot={dashboardData?.macro_snapshot} />
          <KeyInsightsCard valuation={valuation} technicals={technicals} news={news} reportData={reportData} insightPoints={overviewInsight?.key_points} />
          {news && news.length > 0 && <NewsHighlightCard news={news} />}
        </div>

        <div className="space-y-4">
          <AnalystRatingCard technicals={technicals} reportData={reportData} />
          <AgentStatusOverview reportData={reportData} />
          <HighlightsCard valuation={valuation} technicals={technicals} reportData={reportData} />
        </div>

        <div className="space-y-4">
          <DimensionRadar
            valuation={valuation}
            technicals={technicals}
            news={news}
            reportData={reportData}
            valuationFallbackReason={dashboardData?.valuation_fallback_reason}
            financialsFallbackReason={dashboardData?.financials_fallback_reason}
            technicalsFallbackReason={dashboardData?.technicals_fallback_reason}
          />
          <RiskMetricsCard valuation={valuation} reportData={reportData} />
          <AnalystTargetCard
            targets={analystTargets}
            recommendations={recommendations}
            currentPrice={technicals?.close ?? null}
          />
          {peerItems.length > 0 && (
            <PeerSnapshotCard peers={peerItems} subjectSymbol={activeAsset?.symbol} />
          )}
        </div>
      </div>
    </div>
  );
}

export default OverviewTab;

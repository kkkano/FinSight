import { BarChart3, Newspaper, Scale } from 'lucide-react';

import { useDashboardStore } from '../../../store/dashboardStore';
import { DashboardSourceBadge } from '../DashboardSourceBadge';
import { AnalystTargetCard } from './financial/AnalystTargetCard';
import { ValuationGrid } from './financial/ValuationGrid';
import { TechnicalSummaryCard } from './technical/TechnicalSummaryCard';

function formatMarketCap(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '--';
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  return `$${(value / 1e6).toFixed(0)}M`;
}

export function OverviewTab() {
  const dashboardData = useDashboardStore((state) => state.dashboardData);
  const activeAsset = useDashboardStore((state) => state.activeAsset);

  if (!dashboardData) {
    return <div className="py-12 text-center text-sm text-t-text3">正在读取市场快照...</div>;
  }

  const valuation = dashboardData.valuation;
  const technicals = dashboardData.technicals;
  const news = dashboardData.news?.impact?.length
    ? dashboardData.news.impact
    : dashboardData.news?.market ?? [];
  const peers = dashboardData.peers?.peers ?? [];
  const currentPrice = technicals?.close ?? dashboardData.snapshot?.index_level ?? null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-y border-t-border py-2 text-2xs text-t-text3">
        <span className="inline-flex items-center gap-1.5">
          <Scale size={13} className="text-t-accent" />
          概览仅汇总行情、财务和规则指标，不生成第二套 AI 结论
        </span>
        <DashboardSourceBadge metaKey="market_chart" />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <TechnicalSummaryCard technicals={technicals} />
        <ValuationGrid valuation={valuation} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="border-y border-t-border py-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="inline-flex items-center gap-2 text-xs font-semibold text-t-text">
              <Newspaper size={14} className="text-t-info" />
              近期事实
            </h3>
            <DashboardSourceBadge metaKey="news_market" fallbackSource="hybrid_news" />
          </div>
          {news.length === 0 ? (
            <div className="py-5 text-xs text-t-text3">当前没有可核验的近期新闻。</div>
          ) : (
            <ul className="divide-y divide-t-border">
              {news.slice(0, 5).map((item, index) => (
                <li key={`${item.title}-${index}`} className="py-2.5 first:pt-0">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="line-clamp-2 text-xs leading-5 text-t-text2 hover:text-t-accent"
                  >
                    {item.title}
                  </a>
                  <div className="mt-1 text-2xs text-t-text3">
                    {item.source || 'unknown'}{item.ts ? ` · ${new Date(item.ts).toLocaleDateString('zh-CN')}` : ''}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="border-y border-t-border py-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="inline-flex items-center gap-2 text-xs font-semibold text-t-text">
              <BarChart3 size={14} className="text-t-up" />
              同行事实
            </h3>
            <DashboardSourceBadge metaKey="peers" />
          </div>
          {peers.length === 0 ? (
            <div className="py-5 text-xs text-t-text3">
              {dashboardData.peers_fallback_reason || '当前没有可信同行数据。'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-xs">
                <thead className="text-t-text3">
                  <tr className="border-b border-t-border">
                    <th className="pb-2 text-left font-medium">标的</th>
                    <th className="pb-2 text-right font-medium">市盈率</th>
                    <th className="pb-2 text-right font-medium">营收增长</th>
                    <th className="pb-2 text-right font-medium">市值</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-t-border">
                  {peers.slice(0, 6).map((peer) => (
                    <tr key={peer.symbol} className={peer.symbol === activeAsset?.symbol ? 'text-t-accent' : 'text-t-text2'}>
                      <td className="py-2 font-medium">{peer.symbol}</td>
                      <td className="py-2 text-right tabular-nums">{peer.trailing_pe?.toFixed(1) ?? '--'}</td>
                      <td className="py-2 text-right tabular-nums">
                        {peer.revenue_growth == null ? '--' : `${(peer.revenue_growth * 100).toFixed(1)}%`}
                      </td>
                      <td className="py-2 text-right tabular-nums">{formatMarketCap(peer.market_cap)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <AnalystTargetCard
        targets={dashboardData.analyst_targets}
        recommendations={dashboardData.recommendations}
        currentPrice={currentPrice}
      />
    </div>
  );
}

export default OverviewTab;

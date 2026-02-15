/**
 * Dashboard Widgets 容器组件 - 纵向长滚动布局
 *
 * 从上到下依次展示所有卡片，不再使用复杂的网格嵌套。
 */
import { useDashboardStore } from '../../store/dashboardStore';
import { WIDGET_IDS } from '../../types/dashboard';

// 卡片组件
import { SnapshotCard } from '../cards/SnapshotCard';
import { RevenueTrendCard } from '../cards/RevenueTrendCard';
import { SegmentMixCard } from '../cards/SegmentMixCard';
import { SectorWeightsCard } from '../cards/SectorWeightsCard';
import { TopConstituentsCard } from '../cards/TopConstituentsCard';
import { HoldingsCard } from '../cards/HoldingsCard';
import { MarketChartCard } from '../cards/MarketChartCard';
import { MacroCard } from '../cards/MacroCard';
import { NewsFeed } from './NewsFeed';

export function DashboardWidgets() {
  const { activeAsset, capabilities, layoutPrefs, dashboardData, isLoading, resetLayoutPrefs } =
    useDashboardStore();

  const hiddenWidgets = Array.isArray(layoutPrefs?.hidden_widgets)
    ? layoutPrefs.hidden_widgets
    : [];

  // 检查 widget 是否隐藏
  const isHidden = (widgetId: string) => hiddenWidgets.includes(widgetId);

  // 无数据时显示占位
  if (!dashboardData && !isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-fin-muted text-sm">
        请从左侧选择一个资产查看仪表盘
      </div>
    );
  }

  // 加载中占位
  if (isLoading && !dashboardData) {
    return (
      <div className="space-y-4">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="h-48 bg-fin-card border border-fin-border rounded-xl animate-pulse"
          />
        ))}
      </div>
    );
  }

  const snapshot = dashboardData?.snapshot ?? {};
  const charts = dashboardData?.charts ?? {};
  const news = dashboardData?.news ?? { market: [], impact: [] };

  const showSnapshot = !isHidden(WIDGET_IDS.SNAPSHOT);
  const showMarketChart = capabilities?.market_chart !== false && !isHidden(WIDGET_IDS.MARKET_CHART);
  const showNewsFeed = !isHidden(WIDGET_IDS.NEWS_FEED);
  const showRevenueTrend = Boolean(capabilities?.revenue_trend) && !isHidden(WIDGET_IDS.REVENUE_TREND);
  const showSegmentMix = Boolean(capabilities?.segment_mix) && !isHidden(WIDGET_IDS.SEGMENT_MIX);
  const showSectorWeights = Boolean(capabilities?.sector_weights) && !isHidden(WIDGET_IDS.SECTOR_WEIGHTS);
  const showTopConstituents = Boolean(capabilities?.top_constituents) && !isHidden(WIDGET_IDS.TOP_CONSTITUENTS);
  const showHoldings = Boolean(capabilities?.holdings) && !isHidden(WIDGET_IDS.HOLDINGS);
  const showMacro = !isHidden(WIDGET_IDS.MACRO);
  const hasVisibleWidget =
    showSnapshot ||
    showMarketChart ||
    showNewsFeed ||
    showRevenueTrend ||
    showSegmentMix ||
    showSectorWeights ||
    showTopConstituents ||
    showHoldings ||
    showMacro;

  if (!hasVisibleWidget && !isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-fin-muted text-sm gap-3">
        <span>当前布局中所有卡片都被隐藏了</span>
        <button
          type="button"
          onClick={resetLayoutPrefs}
          className="px-3 py-1.5 rounded-lg border border-fin-border bg-fin-card hover:bg-fin-hover transition-colors text-fin-text text-xs"
        >
          重置仪表盘布局
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 1. 核心 KPI 卡片 */}
      {showSnapshot && (
        <SnapshotCard data={snapshot} loading={isLoading} ticker={activeAsset?.symbol} />
      )}

      {/* 2. 价格走势图（支持图表类型和时间范围切换） */}
      {showMarketChart && (
        <MarketChartCard
          data={charts?.market_chart || []}
          loading={isLoading}
        />
      )}

      {/* 3. 新闻动态 */}
      {showNewsFeed && (
        <NewsFeed
          marketNews={news?.market || []}
          impactNews={news?.impact || []}
          marketRawNews={news?.market_raw || []}
          impactRawNews={news?.impact_raw || []}
          rankingFormula={typeof news?.ranking_meta === 'object' ? (news.ranking_meta as { formula?: string }).formula : undefined}
          rankingVersion={typeof news?.ranking_meta === 'object' ? (news.ranking_meta as { version?: string }).version : undefined}
          rankingNotes={
            typeof news?.ranking_meta === 'object' && Array.isArray((news.ranking_meta as { notes?: unknown[] }).notes)
              ? ((news.ranking_meta as { notes?: string[] }).notes || [])
              : []
          }
          loading={isLoading}
        />
      )}

      {/* 4. 营收趋势（股票） */}
      {showRevenueTrend && (
        <RevenueTrendCard
          data={charts?.revenue_trend || []}
          loading={isLoading}
        />
      )}

      {/* 5. 分部收入（股票） */}
      {showSegmentMix && (
        <SegmentMixCard
          data={charts?.segment_mix || []}
          loading={isLoading}
        />
      )}

      {/* 6. 行业权重（ETF/Index） */}
      {showSectorWeights && (
        <SectorWeightsCard
          data={charts?.sector_weights || []}
          loading={isLoading}
        />
      )}

      {/* 7. 成分股 (ETF/Index) */}
      {showTopConstituents && (
        <TopConstituentsCard
          data={charts?.top_constituents || []}
          loading={isLoading}
        />
      )}

      {/* 8. 持仓 (Portfolio) */}
      {showHoldings && (
        <HoldingsCard
          data={charts?.holdings || []}
          loading={isLoading}
        />
      )}

      {/* 9. 宏观指标 */}
      {showMacro && <MacroCard loading={isLoading} />}
    </div>
  );
}

export default DashboardWidgets;

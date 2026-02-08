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
  const { capabilities, layoutPrefs, dashboardData, isLoading } =
    useDashboardStore();

  // 检查 widget 是否隐藏
  const isHidden = (widgetId: string) =>
    layoutPrefs.hidden_widgets.includes(widgetId);

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

  return (
    <div className="space-y-6">
      {/* 1. 核心 KPI 卡片 */}
      {!isHidden(WIDGET_IDS.SNAPSHOT) && (
        <SnapshotCard data={snapshot} loading={isLoading} />
      )}

      {/* 2. 价格走势图（支持图表类型和时间范围切换） */}
      {capabilities?.market_chart !== false && !isHidden(WIDGET_IDS.MARKET_CHART) && (
        <MarketChartCard
          data={charts?.market_chart || []}
          loading={isLoading}
        />
      )}

      {/* 3. 新闻动态 */}
      {!isHidden(WIDGET_IDS.NEWS_FEED) && (
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
      {capabilities?.revenue_trend && !isHidden(WIDGET_IDS.REVENUE_TREND) && (
        <RevenueTrendCard
          data={charts?.revenue_trend || []}
          loading={isLoading}
        />
      )}

      {/* 5. 分部收入（股票） */}
      {capabilities?.segment_mix && !isHidden(WIDGET_IDS.SEGMENT_MIX) && (
        <SegmentMixCard
          data={charts?.segment_mix || []}
          loading={isLoading}
        />
      )}

      {/* 6. 行业权重（ETF/Index） */}
      {capabilities?.sector_weights && !isHidden(WIDGET_IDS.SECTOR_WEIGHTS) && (
        <SectorWeightsCard
          data={charts?.sector_weights || []}
          loading={isLoading}
        />
      )}

      {/* 7. 成分股 (ETF/Index) */}
      {capabilities?.top_constituents && !isHidden(WIDGET_IDS.TOP_CONSTITUENTS) && (
        <TopConstituentsCard
          data={charts?.top_constituents || []}
          loading={isLoading}
        />
      )}

      {/* 8. 持仓 (Portfolio) */}
      {capabilities?.holdings && !isHidden(WIDGET_IDS.HOLDINGS) && (
        <HoldingsCard
          data={charts?.holdings || []}
          loading={isLoading}
        />
      )}

      {/* 9. 宏观指标 */}
      {!isHidden(WIDGET_IDS.MACRO) && <MacroCard loading={isLoading} />}
    </div>
  );
}

export default DashboardWidgets;

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { apiClient, type ReportIndexItem } from '../api/client';
import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import { Card } from '../components/ui/Card';
import { PortfolioSummaryBar } from '../components/workbench/PortfolioSummaryBar';
import { ReportSection } from '../components/workbench/ReportSection';
import { TaskSection } from '../components/workbench/TaskSection';

type WorkbenchProps = {
  symbol: string;
  fromDashboard?: boolean;
  onNavigateToChat?: () => void;
};

export function Workbench({
  symbol,
  fromDashboard = false,
  onNavigateToChat,
}: WorkbenchProps) {
  const navigate = useNavigate();
  const { watchlist } = useDashboardStore();
  const { sessionId } = useStore();

  const [latestReports, setLatestReports] = useState<ReportIndexItem[]>([]);
  const [loadingReports, setLoadingReports] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      setLoadingReports(true);
      try {
        const payload = await apiClient.listReportIndex({
          sessionId,
          limit: 12,
        });
        if (!cancelled) {
          setLatestReports(Array.isArray(payload.items) ? payload.items : []);
        }
      } catch {
        if (!cancelled) {
          setLatestReports([]);
        }
      } finally {
        if (!cancelled) {
          setLoadingReports(false);
        }
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return (
    <div className="space-y-4">
      {/* Breadcrumb / navigation bar */}
      <Card className="px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="text-xs text-fin-muted">
            {fromDashboard
              ? '来源：仪表盘 -> 工作台'
              : '来源：侧边导航 -> 工作台'}
          </div>
          <button
            type="button"
            data-testid="workbench-back-dashboard"
            onClick={() =>
              navigate(`/dashboard/${encodeURIComponent(symbol)}`)
            }
            className="text-xs px-2.5 py-1.5 rounded-lg border border-fin-border hover:border-fin-primary/50 text-fin-text-secondary hover:text-fin-primary transition-colors"
          >
            回工作流上游（仪表盘）
          </button>
        </div>
      </Card>

      {/* Portfolio Summary Bar */}
      <PortfolioSummaryBar />

      {/* Main content: two-column layout */}
      <div className="grid lg:grid-cols-3 gap-4">
        {/* Left: Tasks (main, emphasized) */}
        <div className="lg:col-span-2 space-y-4">
          <TaskSection
            symbol={symbol}
            onNavigateToChat={onNavigateToChat}
          />
        </div>

        {/* Right: Reports (sidebar) */}
        <div className="space-y-4">
          <ReportSection
            symbol={symbol}
            reports={latestReports}
            loading={loadingReports}
          />
        </div>
      </div>
    </div>
  );
}

export default Workbench;

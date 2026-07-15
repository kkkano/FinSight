import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  BriefcaseBusiness,
  FileText,
  ListChecks,
  Newspaper,
  Radar,
} from 'lucide-react';

import { useStore } from '../store/useStore';
import { migrateLegacyPortfolio } from '../utils/portfolioMigration';
import { Card } from '../components/ui/Card';
import { PortfolioSummaryBar } from '../components/workbench/PortfolioSummaryBar';
import { PortfolioPerformance } from '../components/workbench/PortfolioPerformance';
import { PortfolioPieChart } from '../components/workbench/PortfolioPieChart';
import { MorningBriefCard } from '../components/workbench/MorningBriefCard';
import { RebalanceEntryCard } from '../components/workbench/RebalanceEntryCard';
import { ReportSection } from '../components/workbench/ReportSection';
import { TaskSection } from '../components/workbench/TaskSection';
import { TaskCard } from '../components/workbench/TaskCard';
import { FindingsFeed } from '../components/workbench/FindingsFeed';
import { FindingCard } from '../components/workbench/FindingCard';
import { PortfolioEditor } from '../components/workbench/PortfolioEditor';
import { AttributionPanel } from '../components/workbench/AttributionPanel';
import { MonitorConfigPanel } from '../components/workbench/MonitorConfigPanel';
import { MacroCalendarPanel } from '../components/workbench/MacroCalendarPanel';
import { ReportView } from '../components/report/ReportView';
import { WorkbenchQualityDrawer } from '../components/workbench/WorkbenchQualityDrawer';
import { selectTodayQueue } from '../components/workbench/todayQueue';
import { usePortfolioSummary } from '../hooks/usePortfolioSummary';
import { useWorkbenchReport } from '../hooks/useWorkbenchReport';
import { useReportQuality } from '../hooks/useReportQuality';
import { useMorningBrief } from '../hooks/useMorningBrief';
import { useWorkbenchTasks } from '../hooks/useWorkbenchTasks';
import { useFindings } from '../hooks/useFindings';
import { useChatHandoff } from '../hooks/useChatHandoff';
import { resolveFocusHintFromRequirement } from '../utils/reportParsing';

type WorkbenchProps = {
  symbol: string;
  fromDashboard?: boolean;
};

type WorkbenchTab = 'today' | 'portfolio' | 'research' | 'monitor';

const TABS: Array<{
  id: WorkbenchTab;
  label: string;
  Icon: typeof ListChecks;
}> = [
  { id: 'today', label: '今日', Icon: ListChecks },
  { id: 'portfolio', label: '持仓', Icon: BriefcaseBusiness },
  { id: 'research', label: '研究', Icon: FileText },
  { id: 'monitor', label: '监控', Icon: Radar },
];

export function Workbench({ symbol, fromDashboard = false }: WorkbenchProps) {
  const navigate = useNavigate();
  const handoffToChat = useChatHandoff();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedReportId = searchParams.get('report')?.trim() || null;
  const monitorFocusRequested = searchParams.get('focus') === 'monitor';
  const sessionId = useStore((state) => state.sessionId);
  const [activeTab, setActiveTab] = useState<WorkbenchTab>(() => (
    requestedReportId ? 'research' : monitorFocusRequested ? 'monitor' : 'today'
  ));
  const [rebalanceHighlight, setRebalanceHighlight] = useState(false);
  const [qualityDrawerOpen, setQualityDrawerOpen] = useState(false);
  const [qualityFocusHint, setQualityFocusHint] = useState<string | null>(null);

  const portfolioSummary = usePortfolioSummary(sessionId);
  const morningBrief = useMorningBrief(sessionId);
  const findingsController = useFindings(sessionId);
  const tasksController = useWorkbenchTasks(symbol, sessionId);
  const todayQueue = useMemo(
    () => selectTodayQueue(findingsController.findings, tasksController.taskRunItems, 3),
    [findingsController.findings, tasksController.taskRunItems],
  );

  const {
    latestReports,
    loadingReports,
    selectedReportId,
    setSelectedReportId,
    selectedReport,
    loadingSelectedReport,
    selectedReportError,
  } = useWorkbenchReport(sessionId, symbol, requestedReportId);
  const {
    qualityReasons,
    qualityMissing,
    verifierClaims,
    citations,
    showLowGroundingBanner,
    groundingRateText,
    blockedReasons,
    showQualityBlockedBanner,
    reportTicker,
    activeTicker,
    hasTickerMismatch,
  } = useReportQuality(selectedReport, symbol);

  useEffect(() => {
    if (requestedReportId) setActiveTab('research');
    else if (monitorFocusRequested) setActiveTab('monitor');
  }, [monitorFocusRequested, requestedReportId]);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    void migrateLegacyPortfolio(sessionId).then((result) => {
      if (!cancelled && result && result.migrated > 0) void portfolioSummary.refresh();
    });
    return () => {
      cancelled = true;
    };
    // 每个会话只执行一次旧持仓迁移。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const cockpitDate = useMemo(
    () => new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' }).format(new Date()),
    [],
  );
  const lastBriefTime = morningBrief.brief?.generated_at
    ? new Date(morningBrief.brief.generated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : null;

  const handleSelectReport = useCallback((reportId: string) => {
    setActiveTab('research');
    setSelectedReportId(reportId);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('report', reportId);
    setSearchParams(nextParams);
  }, [searchParams, setSearchParams, setSelectedReportId]);

  const handleFindingChat = useCallback((ticker: string, prompt: string) => {
    handoffToChat({
      draft: prompt,
      activeSymbol: ticker,
      sourceView: 'workbench',
      sourceTab: 'monitor',
    });
  }, [handoffToChat]);

  const handleNavigateToRebalance = useCallback(() => {
    setActiveTab('portfolio');
    setRebalanceHighlight(true);
    window.requestAnimationFrame(() => {
      document.getElementById('rebalance-card')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    window.setTimeout(() => setRebalanceHighlight(false), 2000);
  }, []);

  const handleConfigureMonitor = useCallback(() => {
    setActiveTab('monitor');
    window.requestAnimationFrame(() => {
      document.getElementById('monitor-config')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, []);

  const openQualityDrawer = useCallback((focusHint?: string | null) => {
    setQualityFocusHint(focusHint ?? null);
    setQualityDrawerOpen(true);
  }, []);

  return (
    <div className="space-y-5" data-testid="workbench-daily-cockpit">
      <Card className="px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-2xs uppercase tracking-wider text-t-text3">投资工作台</div>
            <div className="mt-1 text-lg font-semibold text-t-text">{cockpitDate}</div>
            <div className="mt-1 text-2xs text-t-text3">
              {fromDashboard ? '来源：仪表盘' : '来源：侧边导航'}
              {lastBriefTime ? ` · 上次晨报 ${lastBriefTime}` : ' · 今日晨报尚未生成'}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => morningBrief.generate()}
              disabled={morningBrief.loading}
              className="inline-flex min-h-11 items-center gap-2 rounded border border-t-accent/50 bg-t-accent/10 px-3 text-xs font-medium text-t-accent hover:bg-t-accent/15 disabled:opacity-50"
              data-testid="workbench-generate-brief"
            >
              <Newspaper size={15} />
              {morningBrief.loading ? '生成中…' : '生成晨报'}
            </button>
            <button
              type="button"
              data-testid="workbench-back-dashboard"
              onClick={() => navigate(symbol ? `/dashboard/${encodeURIComponent(symbol)}` : '/dashboard')}
              className="inline-flex min-h-11 items-center rounded border border-t-border px-3 text-xs text-t-text2 hover:border-t-accent/50 hover:text-t-accent"
            >
              回到看板
            </button>
          </div>
        </div>
      </Card>

      <nav
        aria-label="工作台分区"
        className="grid grid-cols-4 overflow-hidden rounded border border-fin-border bg-fin-card"
        data-testid="workbench-tabs"
      >
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            aria-selected={activeTab === id}
            data-testid={`workbench-tab-${id}`}
            className={`inline-flex min-h-11 items-center justify-center gap-1.5 border-r border-fin-border px-2 text-xs font-medium last:border-r-0 ${
              activeTab === id
                ? 'bg-fin-primary/10 text-fin-primary'
                : 'text-fin-muted hover:bg-fin-hover hover:text-fin-text'
            }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </nav>

      {activeTab === 'today' && (
        <div className="space-y-5" data-testid="workbench-panel-today">
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-fin-text">今日</h2>
            <MorningBriefCard
              brief={morningBrief.brief}
              loading={morningBrief.loading}
              error={morningBrief.error}
              onGenerate={morningBrief.generate}
            />
          </section>

          <section className="space-y-3" data-testid="workbench-today-queue">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-fin-text">待处理</h2>
              <span className="text-2xs text-fin-muted">最多 3 条</span>
            </div>
            {todayQueue.length === 0 ? (
              <div className="border-y border-fin-border py-5 text-xs text-fin-muted">当前没有待处理事项。</div>
            ) : (
              <div className="space-y-2.5">
                {todayQueue.map((item) => item.kind === 'finding' ? (
                  <FindingCard
                    key={item.identity}
                    finding={item.finding}
                    onView={findingsController.markViewed}
                    onNavigateToChat={handleFindingChat}
                    onNavigateToRebalance={handleNavigateToRebalance}
                  />
                ) : (
                  <TaskCard
                    key={item.identity}
                    task={item.taskItem.task}
                    run={item.taskItem.run}
                    onClick={tasksController.handleClick}
                    onResume={tasksController.handleResume}
                    onCancelInterrupt={tasksController.handleCancelInterrupt}
                  />
                ))}
              </div>
            )}
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-fin-text">持仓摘要</h2>
            <PortfolioSummaryBar />
          </section>

          <section className="space-y-3" data-testid="workbench-latest-research">
            <h2 className="text-sm font-semibold text-fin-text">最近研究</h2>
            {loadingReports ? (
              <div className="border-y border-fin-border py-5 text-xs text-fin-muted">正在加载最近研究...</div>
            ) : latestReports[0] ? (
              <button
                type="button"
                onClick={() => handleSelectReport(latestReports[0].report_id)}
                className="flex min-h-14 w-full items-center justify-between gap-3 border-y border-fin-border px-1 py-3 text-left hover:bg-fin-hover"
                data-testid="workbench-latest-report"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-fin-text">
                    {latestReports[0].title || latestReports[0].report_id}
                  </span>
                  <span className="mt-1 block text-2xs text-fin-muted">
                    {latestReports[0].ticker || '综合研究'}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-fin-primary">打开报告</span>
              </button>
            ) : (
              <div className="border-y border-fin-border py-5 text-xs text-fin-muted">暂无最近研究。</div>
            )}
          </section>
        </div>
      )}

      {activeTab === 'portfolio' && (
        <div className="space-y-4" data-testid="workbench-panel-portfolio">
          <div className="grid gap-4 xl:grid-cols-2">
            <PortfolioEditor
              data={portfolioSummary.data}
              loading={portfolioSummary.loading}
              onChanged={portfolioSummary.refresh}
            />
            <div
              id="rebalance-card"
              data-testid="rebalance-card-anchor"
              className={`rounded-lg transition-shadow duration-300 ${
                rebalanceHighlight ? 'ring-2 ring-fin-primary ring-offset-2 ring-offset-fin-bg' : ''
              }`}
            >
              <RebalanceEntryCard />
            </div>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <PortfolioPerformance
              data={portfolioSummary.data}
              loading={portfolioSummary.loading}
              onAddPosition={() => document.getElementById('portfolio-editor-card')?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
            />
            <AttributionPanel data={portfolioSummary.data} loading={portfolioSummary.loading} />
          </div>
          {portfolioSummary.data && portfolioSummary.data.positions.length > 0 && (
            <PortfolioPieChart
              positions={portfolioSummary.data.positions}
              totalValue={portfolioSummary.data.total_value}
            />
          )}
        </div>
      )}

      {activeTab === 'research' && (
        <div className="space-y-4" data-testid="workbench-panel-research">
          <ReportSection
            reports={latestReports}
            loading={loadingReports}
            selectedReportId={selectedReportId}
            onSelectReport={handleSelectReport}
          />

          <Card className="space-y-3 p-4" data-testid="workbench-report-view">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded bg-fin-primary/10 text-fin-primary">
                  <FileText size={16} />
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-fin-text">工作台报告视图</div>
                  <div className="mt-0.5 truncate text-2xs text-fin-muted">已选择报告：{selectedReportId || '--'}</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="min-h-10 rounded border border-fin-border px-3 text-xs text-fin-text hover:bg-fin-border/20 disabled:opacity-50"
                  disabled={!selectedReportId}
                  onClick={() => selectedReportId && navigate(`/chat?report_id=${encodeURIComponent(selectedReportId)}`)}
                >
                  在聊天中打开
                </button>
                <button
                  type="button"
                  className="min-h-10 rounded border border-fin-warning/40 bg-fin-warning/10 px-3 text-xs text-fin-warning hover:bg-fin-warning/20 disabled:opacity-50"
                  onClick={() => openQualityDrawer()}
                  disabled={!selectedReport || (qualityMissing.length === 0 && verifierClaims.length === 0 && qualityReasons.length === 0)}
                  data-testid="workbench-quality-open-drawer"
                >
                  证据质量诊断
                </button>
              </div>
            </div>

            {loadingSelectedReport && <div className="py-5 text-sm text-fin-muted">正在加载报告详情...</div>}
            {!loadingSelectedReport && selectedReportError && <div className="py-3 text-sm text-fin-danger">{selectedReportError}</div>}
            {!loadingSelectedReport && !selectedReportError && !selectedReport && (
              <div className="py-5 text-sm text-fin-muted">请先在报告时间线中选择一份报告。</div>
            )}

            {!loadingSelectedReport && selectedReport && (
              <>
                {hasTickerMismatch && (
                  <div className="border-y border-fin-danger/50 bg-fin-danger/10 px-1 py-3" data-testid="workbench-report-ticker-mismatch">
                    <div className="text-sm font-semibold text-fin-danger">报告标的不匹配，结论区已禁用</div>
                    <div className="mt-1 text-xs text-fin-text/90">当前标的：{activeTicker || '--'}；报告标的：{reportTicker || '--'}。</div>
                  </div>
                )}
                {showQualityBlockedBanner && (
                  <div className="border-y border-fin-danger/50 bg-fin-danger/10 px-1 py-3" data-testid="workbench-report-quality-blocked">
                    <div className="text-sm font-semibold text-fin-danger">报告质量状态：BLOCK（不可发布）</div>
                    {blockedReasons.slice(0, 5).map((item, index) => (
                      <div key={`${item.code}-${index}`} className="mt-1 text-xs text-fin-text/85">{item.message || item.code}</div>
                    ))}
                  </div>
                )}
                {showLowGroundingBanner && (
                  <div className="border-y border-yellow-400/40 bg-yellow-500/10 px-1 py-3 text-sm text-yellow-100" data-testid="workbench-report-grounding-warning">
                    证据溯源率偏低（{groundingRateText}），请先核对引用。
                  </div>
                )}
                {qualityMissing.length > 0 && (
                  <div className="space-y-2 border-y border-fin-warning/40 bg-fin-warning/10 px-1 py-3" data-testid="workbench-report-quality-gap">
                    <div className="text-sm font-semibold text-fin-warning">证据不足（质量门槛未满足）</div>
                    {qualityMissing.slice(0, 6).map((item, index) => (
                      <div key={`${index}-${item}`} className="flex items-start gap-2 text-xs">
                        <span className="min-w-0 flex-1 text-fin-text/85">{item}</span>
                        <button
                          type="button"
                          className="shrink-0 text-fin-primary hover:underline"
                          onClick={() => openQualityDrawer(resolveFocusHintFromRequirement(item))}
                        >
                          查看引用片段
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {verifierClaims.length > 0 && (
                  <div className="border-y border-fin-danger/40 bg-fin-danger/10 px-1 py-3 text-sm text-fin-danger" data-testid="workbench-report-verifier-gap">
                    二次事实核查发现 {verifierClaims.length} 条断言缺口
                  </div>
                )}
                {hasTickerMismatch ? (
                  <div className="py-6 text-sm text-fin-muted" data-testid="workbench-report-conclusion-disabled">
                    结论区已禁用：请先修复串票后再查看完整深度报告。
                  </div>
                ) : (
                  <ReportView report={selectedReport} />
                )}
              </>
            )}
          </Card>
        </div>
      )}

      {activeTab === 'monitor' && (
        <div className="space-y-4" data-testid="workbench-panel-monitor">
          <div className="grid gap-4 xl:grid-cols-2">
            <FindingsFeed
              controller={findingsController}
              onNavigateToChat={handleFindingChat}
              onNavigateToRebalance={handleNavigateToRebalance}
              onConfigureMonitor={handleConfigureMonitor}
            />
            <TaskSection controller={tasksController} />
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <div id="monitor-config" data-testid="workbench-monitor-config">
              <MonitorConfigPanel sessionId={sessionId} />
            </div>
            <MacroCalendarPanel sessionId={sessionId} />
          </div>
        </div>
      )}

      <WorkbenchQualityDrawer
        open={qualityDrawerOpen}
        onClose={() => setQualityDrawerOpen(false)}
        qualityMissing={qualityMissing}
        verifierClaims={verifierClaims}
        citations={citations}
        initialFocusHint={qualityFocusHint}
      />
    </div>
  );
}

export default Workbench;

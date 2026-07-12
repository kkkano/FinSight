import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { FileText, Newspaper } from 'lucide-react';

import { useStore } from '../store/useStore';
import { useDashboardStore } from '../store/dashboardStore';
import { migrateLegacyPortfolio } from '../utils/portfolioMigration';
import { Card } from '../components/ui/Card';
import { PortfolioSummaryBar } from '../components/workbench/PortfolioSummaryBar';
import { PortfolioPerformance } from '../components/workbench/PortfolioPerformance';
import { PortfolioPieChart } from '../components/workbench/PortfolioPieChart';
import { MorningBriefCard } from '../components/workbench/MorningBriefCard';
import { RebalanceEntryCard } from '../components/workbench/RebalanceEntryCard';
import { ReportSection } from '../components/workbench/ReportSection';
import { TaskSection } from '../components/workbench/TaskSection';
import { FindingsFeed } from '../components/workbench/FindingsFeed';
import { PortfolioEditor } from '../components/workbench/PortfolioEditor';
import { AttributionPanel } from '../components/workbench/AttributionPanel';
import { MonitorConfigPanel } from '../components/workbench/MonitorConfigPanel';
import { MacroCalendarPanel } from '../components/workbench/MacroCalendarPanel';
import { ReportView } from '../components/report/ReportView';
import { WorkbenchQualityDrawer } from '../components/workbench/WorkbenchQualityDrawer';
import { usePortfolioSummary } from '../hooks/usePortfolioSummary';
import { useWorkbenchReport } from '../hooks/useWorkbenchReport';
import { useReportQuality } from '../hooks/useReportQuality';
import { useMorningBrief } from '../hooks/useMorningBrief';
import { resolveFocusHintFromRequirement } from '../utils/reportParsing';

type WorkbenchProps = {
  symbol: string;
  fromDashboard?: boolean;
  onNavigateToChat?: () => void;
};

function CockpitSectionHeader({
  index,
  title,
  description,
}: {
  index: number;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-end justify-between gap-3 border-b border-t-border pb-2">
      <div>
        <div className="text-2xs uppercase tracking-wider text-t-text3">0{index} · {title}</div>
        <p className="mt-1 text-xs text-t-text2">{description}</p>
      </div>
    </div>
  );
}

// ==================== 页面主体 ====================

export function Workbench({
  symbol,
  fromDashboard = false,
  onNavigateToChat,
}: WorkbenchProps) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedReportId = searchParams.get('report')?.trim() || null;
  const monitorFocusRequested = searchParams.get('focus') === 'monitor';
  const { sessionId, setDraft } = useStore();
  const setActiveAsset = useDashboardStore((state) => state.setActiveAsset);
  const portfolioSummary = usePortfolioSummary(sessionId);

  const {
    latestReports,
    loadingReports,
    selectedReportId,
    setSelectedReportId,
    selectedReport,
    loadingSelectedReport,
    selectedReportError,
  } = useWorkbenchReport(sessionId, symbol, requestedReportId);

  const handleSelectReport = useCallback((reportId: string) => {
    setSelectedReportId(reportId);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('report', reportId);
    setSearchParams(nextParams);
  }, [searchParams, setSearchParams, setSelectedReportId]);

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

  const [qualityDrawerOpen, setQualityDrawerOpen] = useState(false);
  const [qualityFocusHint, setQualityFocusHint] = useState<string | null>(null);

  // 调仓卡片高亮态：发现卡片「调仓建议」联动时短暂高亮 2 秒
  const [rebalanceHighlight, setRebalanceHighlight] = useState(false);

  // 一键晨报
  const morningBrief = useMorningBrief(sessionId);
  const cockpitDate = useMemo(
    () => new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' }).format(new Date()),
    [],
  );
  const lastBriefTime = morningBrief.brief?.generated_at
    ? new Date(morningBrief.brief.generated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : null;

  // 旧版 localStorage 持仓 → 后端一次性迁移（工作台是持仓主场景，挂载时执行一次）。
  // 仅当本地有数据且后端为空时迁移，迁移成功后清除本地 key 并刷新 summary。
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    void migrateLegacyPortfolio(sessionId).then((result) => {
      if (!cancelled && result && result.migrated > 0) {
        void portfolioSummary.refresh();
      }
    });
    return () => {
      cancelled = true;
    };
    // 仅依赖 sessionId：每个会话只迁移一次。portfolioSummary.refresh 引用稳定，无需入依赖。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (!monitorFocusRequested) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById('monitor-config')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [monitorFocusRequested]);

  const openQualityDrawer = useCallback((focusHint?: string | null) => {
    setQualityFocusHint(focusHint ?? null);
    setQualityDrawerOpen(true);
  }, []);

  const handleOpenInChat = useCallback(() => {
    if (!selectedReportId) return;
    navigate(`/chat?report_id=${encodeURIComponent(selectedReportId)}`);
  }, [navigate, selectedReportId]);

  // 发现卡片「看完整简报」→ 携带完整发现与 ticker 跳转 Chat。
  const handleNavigateToChatWithTicker = useCallback(
    (ticker: string, prompt: string) => {
      const normalized = ticker.trim().toUpperCase();
      if (normalized) {
        setActiveAsset({
          symbol: normalized,
          type: 'equity',
          display_name: normalized,
        });
      }
      setDraft(prompt);
      navigate(`/chat?prompt=${encodeURIComponent(prompt)}`);
    },
    [navigate, setActiveAsset, setDraft],
  );

  // 发现卡片「调仓建议」→ 滚动到调仓卡片并短暂高亮（2 秒后取消）
  const handleNavigateToRebalance = useCallback(() => {
    const el = document.getElementById('rebalance-card');
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    setRebalanceHighlight(true);
    window.setTimeout(() => setRebalanceHighlight(false), 2000);
  }, []);

  return (
    <div className="space-y-7" data-testid="workbench-daily-cockpit">
      <Card className="px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-2xs uppercase tracking-wider text-t-text3">今日驾驶舱</div>
            <div className="mt-1 text-lg font-semibold text-t-text">今日 · {cockpitDate}</div>
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

      <section className="space-y-3" data-testid="cockpit-section-brief">
        <CockpitSectionHeader index={1} title="晨报速览" description="先看隔夜变化、持仓异动与今日建议。" />
        <MorningBriefCard
          brief={morningBrief.brief}
          loading={morningBrief.loading}
          error={morningBrief.error}
          onGenerate={morningBrief.generate}
        />
      </section>

      <section className="space-y-3" data-testid="cockpit-section-attention">
        <CockpitSectionHeader index={2} title="需要你注意" description="真实监控发现、今日任务与未来事件；没有信号时就保持安静。" />
        <div className="grid gap-4 xl:grid-cols-2">
          <FindingsFeed
            sessionId={sessionId}
            onNavigateToChat={handleNavigateToChatWithTicker}
            onNavigateToRebalance={handleNavigateToRebalance}
            onConfigureMonitor={() => document.getElementById('monitor-config')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
          />
          <TaskSection symbol={symbol} onNavigateToChat={onNavigateToChat} />
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <div id="monitor-config" data-testid="workbench-monitor-config">
            <MonitorConfigPanel sessionId={sessionId} />
          </div>
          <MacroCalendarPanel sessionId={sessionId} />
        </div>
      </section>

      <section className="space-y-3" data-testid="cockpit-section-portfolio">
        <CockpitSectionHeader index={3} title="我的持仓" description="从组合总览进入持仓管理、归因与再平衡。" />
        <PortfolioSummaryBar />
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
      </section>

      <section className="space-y-3" data-testid="cockpit-section-archive">
        <CockpitSectionHeader index={4} title="研究归档" description="回放、追问、对比或回测最近报告。" />
        <ReportSection
          reports={latestReports}
          loading={loadingReports}
          selectedReportId={selectedReportId}
          onSelectReport={handleSelectReport}
        />

      <Card className="p-4 space-y-3" data-testid="workbench-report-view">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2.5">
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-fin-primary/10 text-fin-primary">
              <FileText size={16} />
            </span>
            <div>
              <div className="text-sm font-semibold text-fin-text">工作台报告视图</div>
              <div className="text-2xs text-fin-muted mt-0.5">
                已选择报告：{selectedReportId || '--'}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="px-3 py-1.5 rounded-lg border border-fin-border text-xs text-fin-text hover:bg-fin-border/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={!selectedReportId}
              onClick={handleOpenInChat}
            >
              在聊天中打开
            </button>
            <button
              type="button"
              className="px-3 py-1.5 rounded-lg border border-fin-warning/40 bg-fin-warning/10 text-xs text-fin-warning hover:bg-fin-warning/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={() => openQualityDrawer()}
              disabled={!selectedReport || (qualityMissing.length === 0 && verifierClaims.length === 0 && qualityReasons.length === 0)}
              data-testid="workbench-quality-open-drawer"
            >
              证据质量诊断
            </button>
          </div>
        </div>

        {loadingSelectedReport && (
          <div className="rounded-lg border border-fin-border bg-fin-card/60 px-4 py-5 text-sm text-fin-muted" data-testid="workbench-report-loading">
            正在加载报告详情...
          </div>
        )}

        {!loadingSelectedReport && selectedReportError && (
          <div className="rounded-lg border border-fin-danger/40 bg-fin-danger/10 px-4 py-3 text-sm text-fin-danger" data-testid="workbench-report-error">
            {selectedReportError}
          </div>
        )}

        {!loadingSelectedReport && !selectedReportError && !selectedReport && (
          <div className="rounded-lg border border-fin-border bg-fin-card/60 px-4 py-5 text-sm text-fin-muted" data-testid="workbench-report-empty">
            请先在右侧报告时间线中选择一份报告。
          </div>
        )}

        {!loadingSelectedReport && selectedReport && (
          <>
            {hasTickerMismatch && (
              <div
                className="rounded-lg border border-fin-danger/50 bg-fin-danger/10 px-4 py-3"
                data-testid="workbench-report-ticker-mismatch"
              >
                <div className="text-sm font-semibold text-fin-danger">
                  ⚠ 报告标的不匹配，结论区已禁用
                </div>
                <div className="mt-1 text-xs text-fin-text/90">
                  当前标的：{activeTicker || '--'}；报告标的：{reportTicker || '--'}。为避免串票误导，已阻断结论展示。
                </div>
              </div>
            )}

            {showQualityBlockedBanner && (
              <div
                className="rounded-lg border border-fin-danger/50 bg-fin-danger/10 px-4 py-3"
                data-testid="workbench-report-quality-blocked"
              >
                <div className="text-sm font-semibold text-fin-danger">
                  报告质量状态：BLOCK（不可发布）
                </div>
                <div className="mt-1 text-xs text-fin-text/85">
                  以下硬阈值未满足，请先补齐证据后再复用该报告。
                </div>
                {blockedReasons.length > 0 && (
                  <div className="mt-2 space-y-1 text-xs text-fin-text/85">
                    {blockedReasons.slice(0, 5).map((item, idx) => (
                      <div key={`${item.code}-${idx}`}>
                        <div>• {item.message || item.code}</div>
                        <div className="text-2xs text-fin-text/65">
                          code={item.code}
                          {item.metric ? ` | metric=${item.metric}` : ''}
                          {item.actual !== undefined ? ` | actual=${String(item.actual)}` : ''}
                          {item.threshold !== undefined ? ` | threshold=${String(item.threshold)}` : ''}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {showLowGroundingBanner && (
              <div
                className="rounded-lg border border-yellow-400/40 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-100"
                data-testid="workbench-report-grounding-warning"
              >
                <div className="font-medium">⚠ 证据溯源率偏低（{groundingRateText}）</div>
                <div className="mt-1 text-xs text-yellow-100/85">
                  当前结论中存在较多缺少直接证据锚点的断言，建议优先核对引用列表与正文摘录后再决策。
                </div>
              </div>
            )}

            {qualityMissing.length > 0 && (
              <div
                className="rounded-lg border border-fin-warning/40 bg-fin-warning/10 px-4 py-3"
                data-testid="workbench-report-quality-gap"
              >
                <div className="text-sm font-semibold text-fin-warning">证据不足（质量门槛未满足）</div>
                <div className="mt-1 text-xs text-fin-text/80">
                  可直接定位到引用片段核对，不需要"问这条"。
                </div>
                <div className="mt-2 space-y-2">
                  {qualityMissing.slice(0, 6).map((item, idx) => (
                    <div key={`${idx}-${item}`} className="flex items-start gap-2 text-xs">
                      <span className="text-fin-warning mt-0.5">•</span>
                      <span className="flex-1 text-fin-text/85">{item}</span>
                      <button
                        type="button"
                        className="shrink-0 px-2 py-0.5 rounded border border-fin-border text-fin-primary hover:bg-fin-primary/10 transition-colors"
                        onClick={() => openQualityDrawer(resolveFocusHintFromRequirement(item))}
                        data-testid={`workbench-quality-focus-${idx}`}
                      >
                        查看引用片段
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {verifierClaims.length > 0 && (
              <div
                className="rounded-lg border border-fin-danger/40 bg-fin-danger/10 px-4 py-3"
                data-testid="workbench-report-verifier-gap"
              >
                <div className="text-sm font-semibold text-fin-danger">
                  二次事实核查发现 {verifierClaims.length} 条断言缺口
                </div>
                <div className="mt-1 text-xs text-fin-text/85">
                  建议优先点击"证据质量诊断"定位对应引用片段。
                </div>
              </div>
            )}

            {hasTickerMismatch ? (
              <div
                className="rounded-lg border border-fin-border bg-fin-card/60 px-4 py-6 text-sm text-fin-muted"
                data-testid="workbench-report-conclusion-disabled"
              >
                结论区已禁用：请先修复串票后再查看完整深度报告。
              </div>
            ) : (
              <ReportView report={selectedReport} />
            )}
          </>
        )}
      </Card>
      </section>

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

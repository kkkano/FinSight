import { useCallback, useEffect, useMemo, useRef } from 'react';

import { useExecuteAgent } from './useExecuteAgent';
import { useDashboardStore } from '../store/dashboardStore';
import { useExecutionStore } from '../store/executionStore';
import type { DashboardData, InsightCard } from '../types/dashboard';
import type { ExecutionRun } from '../types/execution';
import {
  buildDashboardAgentOverlay,
  buildDashboardOverlayKey,
  type DashboardAgentOverlay,
  type DashboardDeepDiveTab,
} from '../utils/dashboardDeepDiveOverlay';

const TAB_LABELS: Record<DashboardDeepDiveTab, string> = {
  overview: '综合概览',
  financial: '财务/基本面',
  news: '新闻',
  peers: '同行对比',
  technical: '技术面',
};

interface UseDashboardDeepDiveOptions {
  tab: DashboardDeepDiveTab;
  metric?: string | null;
  insight?: InsightCard | null;
  snapshot?: Record<string, unknown> | null;
  userQuestion?: string | null;
}

interface UseDashboardDeepDiveResult {
  overlay: DashboardAgentOverlay | null;
  run: ExecutionRun | null;
  isRunning: boolean;
  progress: number;
  currentStep: string | null;
  startDeepDive: (overrideQuestion?: string) => void;
}

function limitArray<T>(items: T[] | null | undefined, limit: number): T[] {
  if (!Array.isArray(items)) return [];
  return items.slice(0, limit);
}

function tailArray<T>(items: T[] | null | undefined, limit: number): T[] {
  if (!Array.isArray(items)) return [];
  return items.slice(Math.max(0, items.length - limit));
}

function buildDashboardTabSnapshot(
  tab: DashboardDeepDiveTab,
  dashboardData: DashboardData | null,
  insight?: InsightCard | null,
): Record<string, unknown> | null {
  if (!dashboardData) return insight ? { insight } : null;

  const common = {
    snapshot: dashboardData.snapshot,
    insight: insight ?? null,
    data_quality: {
      valuation_fallback_reason: dashboardData.valuation_fallback_reason ?? null,
      financials_fallback_reason: dashboardData.financials_fallback_reason ?? null,
      technicals_fallback_reason: dashboardData.technicals_fallback_reason ?? null,
      peers_fallback_reason: dashboardData.peers_fallback_reason ?? null,
      macro_snapshot_fallback_reason: dashboardData.macro_snapshot_fallback_reason ?? null,
    },
  };

  if (tab === 'financial') {
    return {
      ...common,
      financials: dashboardData.financials ?? null,
      valuation: dashboardData.valuation ?? null,
      earnings_history: limitArray(dashboardData.earnings_history, 8),
      analyst_targets: dashboardData.analyst_targets ?? null,
      recommendations: dashboardData.recommendations ?? null,
    };
  }

  if (tab === 'technical') {
    return {
      ...common,
      technicals: dashboardData.technicals ?? null,
      indicator_series: dashboardData.indicator_series ?? null,
      market_chart: tailArray(dashboardData.charts?.market_chart, 120),
    };
  }

  if (tab === 'news') {
    return {
      ...common,
      news: {
        market: limitArray(dashboardData.news?.market, 16),
        impact: limitArray(dashboardData.news?.impact, 16),
        ranking_meta: dashboardData.news?.ranking_meta,
      },
    };
  }

  if (tab === 'peers') {
    return {
      ...common,
      peers: dashboardData.peers
        ? {
            ...dashboardData.peers,
            peers: limitArray(dashboardData.peers.peers, 8),
          }
        : null,
      valuation: dashboardData.valuation ?? null,
      technicals: dashboardData.technicals ?? null,
    };
  }

  return {
    ...common,
    valuation: dashboardData.valuation ?? null,
    technicals: dashboardData.technicals ?? null,
    macro_snapshot: dashboardData.macro_snapshot ?? null,
    earnings_history: limitArray(dashboardData.earnings_history, 4),
    analyst_targets: dashboardData.analyst_targets ?? null,
    recommendations: dashboardData.recommendations ?? null,
    peers: limitArray(dashboardData.peers?.peers, 6),
    news: {
      market: limitArray(dashboardData.news?.market, 8),
      impact: limitArray(dashboardData.news?.impact, 8),
    },
  };
}

export function useDashboardDeepDive({
  tab,
  metric,
  insight,
  snapshot,
  userQuestion,
}: UseDashboardDeepDiveOptions): UseDashboardDeepDiveResult {
  const activeAsset = useDashboardStore((s) => s.activeAsset);
  const dashboardData = useDashboardStore((s) => s.dashboardData);
  const setOverlay = useDashboardStore((s) => s.setOverlay);
  const symbol = activeAsset?.symbol?.trim().toUpperCase() ?? '';
  const overlay = useDashboardStore((s) => (
    symbol
      ? s.agentOverlaysBySymbolTab[buildDashboardOverlayKey(symbol, tab)] ?? null
      : null
  ));

  const { execute, runId: localRunId } = useExecuteAgent();
  const trackedRunId = localRunId ?? (
    overlay?.status === 'running' || overlay?.status === 'interrupted'
      ? overlay.runId
      : null
  );

  const run = useExecutionStore((s) => {
    if (!trackedRunId) return null;
    return (
      s.activeRuns.find((item) => item.runId === trackedRunId)
      ?? s.recentRuns.find((item) => item.runId === trackedRunId)
      ?? null
    );
  });
  const overlayRunning = overlay?.status === 'running' || overlay?.status === 'interrupted';

  const resolvedSnapshot = useMemo(
    () => snapshot ?? buildDashboardTabSnapshot(tab, dashboardData, insight),
    [dashboardData, insight, snapshot, tab],
  );

  const lastSyncedKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!symbol || !run) return;

    if (run.status === 'running' || run.status === 'interrupted') {
      const syncKey = `${run.runId}:${run.status}`;
      if (lastSyncedKeyRef.current === syncKey) return;
      lastSyncedKeyRef.current = syncKey;
      setOverlay(symbol, tab, buildDashboardAgentOverlay(run));
      return;
    }

    const syncKey = `${run.runId}:${run.status}:${run.completedAt ?? run.error ?? ''}`;
    if (lastSyncedKeyRef.current === syncKey) return;
    lastSyncedKeyRef.current = syncKey;
    setOverlay(symbol, tab, buildDashboardAgentOverlay(run));
  }, [run, setOverlay, symbol, tab]);

  const startDeepDive = useCallback((overrideQuestion?: string) => {
    if (!symbol || overlayRunning || run?.status === 'running' || run?.status === 'interrupted') return;

    const effectiveQuestion = overrideQuestion ?? userQuestion ?? null;
    const label = TAB_LABELS[tab];
    const query = `Dashboard ${label} 深挖：${symbol}${metric ? ` / ${metric}` : ''}`;
    const runId = execute({
      query,
      tickers: [symbol],
      outputMode: 'investment_report',
      confirmationMode: 'skip',
      analysisDepth: 'report',
      source: `dashboard_deep_dive_${tab}`,
      endpoint: '/api/dashboard/deep-dive',
      requestBody: {
        symbol,
        tab,
        ...(metric ? { metric } : {}),
        ...(resolvedSnapshot ? { dashboard_snapshot: resolvedSnapshot } : {}),
        ...(effectiveQuestion ? { user_question: effectiveQuestion } : {}),
      },
    });

    setOverlay(symbol, tab, {
      runId,
      status: 'running',
      summary: 'Agent 深挖已启动，正在编排工具与研究 Agent。',
      claims: [],
      updatedAt: new Date().toISOString(),
    });
    lastSyncedKeyRef.current = `${runId}:running`;
  }, [execute, metric, overlayRunning, resolvedSnapshot, run?.status, setOverlay, symbol, tab, userQuestion]);

  return {
    overlay,
    run,
    isRunning: run?.status === 'running' || run?.status === 'interrupted' || overlayRunning,
    progress: run?.progress ?? (overlayRunning ? 0 : overlay?.status === 'done' ? 100 : 0),
    currentStep: run?.currentStep ?? (overlayRunning ? overlay?.summary ?? null : null),
    startDeepDive,
  };
}

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  BarChart3,
  CalendarClock,
  Database,
  FileText,
  History,
  MessageSquare,
  RefreshCw,
  Target,
} from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { apiClient, type ReportIndexItem } from '../api/client';
import type { PredictionHistoryItem, PredictionStatBucket } from '../api/domains/predictions';
import { ReportView } from '../components/report';
import { usePredictionHistory, usePredictionRun } from '../hooks/usePredictionHistory';
import { useStore } from '../store/useStore';
import type { ReportIR } from '../types';

type HistoryTab = 'predictions' | 'reports';

const DIRECTION_LABELS = {
  long: 'LONG · 偏多',
  short: 'SHORT · 偏空',
  neutral: 'NEUTRAL · 中性',
} as const;

const DIRECTION_CLASSES = {
  long: 'border-t-up/35 bg-t-up/10 text-t-up',
  short: 'border-t-down/35 bg-t-down/10 text-t-down',
  neutral: 'border-t-border bg-t-hover text-t-text2',
} as const;

const OUTCOME_LABELS: Record<string, string> = {
  waiting: '等待入场',
  open: '进行中',
  triggered: '已触发',
  invalidated: '已失效',
  hit_target: '目标达成',
  hit_stop: '止损触发',
  held_range: '区间成立',
  broke_range: '区间突破',
  data_pending: '等待行情',
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function formatPrice(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '--';
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
  return `${(value <= 1 ? value * 100 : value).toFixed(1)}%`;
}

function resolveBucket(
  buckets: Record<string, PredictionStatBucket> | undefined,
  key: string,
): PredictionStatBucket | null {
  return buckets?.[key] ?? null;
}

function StatCell({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="min-w-0 border-r border-t-border px-4 last:border-r-0 max-sm:border-b max-sm:border-r-0 max-sm:py-3 max-sm:last:border-b-0">
      <div className="text-2xs uppercase text-t-text3">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-t-text">{value}</div>
      {detail ? <div className="mt-0.5 truncate text-2xs text-t-text3">{detail}</div> : null}
    </div>
  );
}

function PredictionListItem({
  item,
  active,
  onSelect,
}: {
  item: PredictionHistoryItem;
  active: boolean;
  onSelect: () => void;
}) {
  const { prediction, outcome } = item;
  const status = outcome?.status || prediction.status;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full border-b border-t-border px-4 py-3 text-left transition-colors last:border-b-0 ${
        active ? 'bg-t-accent/10' : 'hover:bg-t-hover'
      }`}
      data-testid="prediction-history-item"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-t-text">{prediction.symbol}</span>
        <span className={`rounded border px-1.5 py-0.5 text-2xs font-semibold ${DIRECTION_CLASSES[prediction.direction]}`}>
          {DIRECTION_LABELS[prediction.direction]}
        </span>
      </div>
      <div className="mt-2 flex items-center justify-between gap-3 text-2xs text-t-text3">
        <span>{formatDateTime(prediction.created_at)}</span>
        <span>{OUTCOME_LABELS[status] || status}</span>
      </div>
      <div className="mt-2 line-clamp-2 text-xs leading-5 text-t-text2">{prediction.thesis}</div>
    </button>
  );
}

function PredictionDetail({ item }: { item: PredictionHistoryItem | null }) {
  const navigate = useNavigate();
  const prediction = item?.prediction ?? null;
  const outcome = item?.outcome ?? null;
  const run = usePredictionRun(prediction?.run_id);

  if (!prediction) {
    return <div className="flex h-full min-h-56 items-center justify-center text-sm text-t-text3">选择一条 AI 判断查看详情</div>;
  }

  const status = outcome?.status || prediction.status;
  const levels = [
    ['锚点', prediction.anchor.price],
    ['入场', prediction.entry],
    ['止损', prediction.stop],
    ['目标 1', prediction.target1],
    ['目标 2', prediction.target2],
  ] as const;

  return (
    <div className="h-full overflow-y-auto px-5 py-4 max-sm:px-4" data-testid="prediction-history-detail">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-t-border pb-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold text-t-text">{prediction.symbol}</h2>
            <span className={`rounded border px-2 py-0.5 text-2xs font-semibold ${DIRECTION_CLASSES[prediction.direction]}`}>
              {DIRECTION_LABELS[prediction.direction]}
            </span>
            <span className="rounded border border-t-border px-2 py-0.5 text-2xs text-t-text2">
              {OUTCOME_LABELS[status] || status}
            </span>
          </div>
          <div className="mt-1 text-2xs text-t-text3">创建于 {formatDateTime(prediction.created_at)}</div>
        </div>
        <button
          type="button"
          onClick={() => navigate(`/dashboard/${encodeURIComponent(prediction.symbol)}?analysis=prediction&predictionId=${encodeURIComponent(prediction.prediction_id)}`)}
          className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-t-border px-3 text-xs text-t-text2 hover:border-t-accent/50 hover:text-t-text"
        >
          打开看板 <ArrowRight size={13} />
        </button>
      </div>

      <p className="mt-4 text-sm leading-6 text-t-text2">{prediction.thesis}</p>

      <div className="mt-5 grid grid-cols-2 border-y border-t-border py-3 sm:grid-cols-5">
        {levels.map(([label, value]) => (
          <div key={label} className="border-r border-t-border px-3 last:border-r-0 max-sm:py-2">
            <div className="text-2xs text-t-text3">{label}</div>
            <div className="mt-1 text-sm font-semibold tabular-nums text-t-text">{formatPrice(value)}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <section>
          <h3 className="text-xs font-semibold text-t-text">Outcome</h3>
          <dl className="mt-2 space-y-2 text-xs">
            <div className="flex justify-between gap-4"><dt className="text-t-text3">结果</dt><dd className="text-right text-t-text2">{OUTCOME_LABELS[status] || status}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-t-text3">锚点后变动</dt><dd className="text-right tabular-nums text-t-text2">{formatPercent(outcome?.pct_since_anchor)}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-t-text3">评估至</dt><dd className="text-right text-t-text2">{formatDateTime(outcome?.evaluated_through)}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-t-text3">算法</dt><dd className="text-right text-t-text2">{outcome?.algorithm_version || '--'}</dd></div>
          </dl>
        </section>
        <section>
          <h3 className="text-xs font-semibold text-t-text">运行来源</h3>
          <dl className="mt-2 space-y-2 text-xs">
            <div className="flex justify-between gap-4"><dt className="text-t-text3">行情</dt><dd className="text-right text-t-text2">{prediction.evidence_provider || run?.market_provider || '--'}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-t-text3">证据时间</dt><dd className="text-right text-t-text2">{formatDateTime(prediction.evidence_as_of || run?.market_as_of)}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-t-text3">模型</dt><dd className="text-right text-t-text2">{run?.llm_provider && run.llm_model ? `${run.llm_provider} / ${run.llm_model}` : '--'}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-t-text3">Prompt</dt><dd className="text-right text-t-text2">{prediction.prompt_version}</dd></div>
          </dl>
        </section>
      </div>

      {prediction.scenarios.length > 0 ? (
        <section className="mt-5 border-t border-t-border pt-4">
          <h3 className="text-xs font-semibold text-t-text">情景</h3>
          <div className="mt-2 space-y-2">
            {prediction.scenarios.map((scenario) => (
              <div key={`${scenario.name}-${scenario.probability}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b border-t-border pb-2 text-xs last:border-b-0">
                <div>
                  <div className="text-t-text2">{scenario.name}</div>
                  <div className="mt-1 text-t-text3">失效条件：{scenario.invalidation}</div>
                </div>
                <div className="tabular-nums text-t-text2">{formatPercent(scenario.probability)}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function PredictionHistoryPanel() {
  const { items, stats, loading, failure, refresh } = usePredictionHistory();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (selectedId && items.some((item) => item.prediction.prediction_id === selectedId)) return;
    setSelectedId(items[0]?.prediction.prediction_id ?? null);
  }, [items, selectedId]);

  const selected = useMemo(
    () => items.find((item) => item.prediction.prediction_id === selectedId) ?? null,
    [items, selectedId],
  );
  const aiBucket = resolveBucket(stats?.by_source, 'ai');

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="grid shrink-0 border border-t-border bg-t-surface py-3 sm:grid-cols-4">
        <StatCell label="90 天判断" value={String(aiBucket?.predictions ?? stats?.predictions ?? 0)} detail="AI 与人工记录分桶统计" />
        <StatCell label="已结算" value={String(aiBucket?.resolved ?? stats?.resolved ?? 0)} detail="未结项不进入命中率" />
        <StatCell label="命中率" value={formatPercent(aiBucket?.hit_rate ?? stats?.hit_rate)} detail={`${aiBucket?.hits ?? stats?.hits ?? 0} 命中 · ${aiBucket?.misses ?? stats?.misses ?? 0} 未命中`} />
        <StatCell label="方向" value={String(Object.keys(stats?.by_direction ?? {}).length)} detail="LONG / SHORT / NEUTRAL" />
      </div>

      {failure ? (
        <div className="flex items-center justify-between gap-3 border border-t-down/30 bg-t-down/10 px-4 py-3 text-xs text-t-down">
          <span>{failure.message} [{failure.code}]</span>
          <button type="button" onClick={refresh} className="inline-flex items-center gap-1"><RefreshCw size={13} />重试</button>
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 overflow-hidden border border-t-border bg-t-surface lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="min-h-0 overflow-y-auto border-r border-t-border max-lg:max-h-72 max-lg:border-b max-lg:border-r-0">
          {loading ? (
            <div className="flex min-h-40 items-center justify-center gap-2 text-xs text-t-text3"><RefreshCw size={14} className="animate-spin" />读取 Prediction 历史...</div>
          ) : items.length === 0 ? (
            <div className="flex min-h-40 flex-col items-center justify-center px-6 text-center text-xs text-t-text3">
              <Target size={20} className="mb-2" />
              尚无 AI 判断历史，请先在看板生成。
            </div>
          ) : items.map((item) => (
            <PredictionListItem
              key={item.prediction.prediction_id}
              item={item}
              active={item.prediction.prediction_id === selectedId}
              onSelect={() => setSelectedId(item.prediction.prediction_id)}
            />
          ))}
        </div>
        <PredictionDetail item={selected} />
      </div>
    </div>
  );
}

function ReportsHistoryPanel({ initialReportId }: { initialReportId: string | null }) {
  const navigate = useNavigate();
  const sessionId = useStore((state) => state.sessionId);
  const [items, setItems] = useState<ReportIndexItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialReportId);
  const [report, setReport] = useState<ReportIR | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingReport, setLoadingReport] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestKey, setRequestKey] = useState(0);
  const refresh = useCallback(() => setRequestKey((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoadingList(true);
    setError(null);
    void apiClient.listReportIndex({ sessionId, limit: 100 })
      .then((payload) => {
        if (cancelled) return;
        const next = Array.isArray(payload.items) ? payload.items : [];
        setItems(next);
        setSelectedId((current) => current && next.some((item) => item.report_id === current) ? current : next[0]?.report_id ?? null);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : '报告历史读取失败');
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false);
      });
    return () => { cancelled = true; };
  }, [requestKey, sessionId]);

  useEffect(() => {
    if (!selectedId) {
      setReport(null);
      return undefined;
    }
    let cancelled = false;
    setLoadingReport(true);
    setError(null);
    void apiClient.getReportReplay({ sessionId, reportId: selectedId })
      .then((payload) => {
        if (!cancelled) setReport(payload.report as ReportIR);
      })
      .catch((reason) => {
        if (!cancelled) {
          setReport(null);
          setError(reason instanceof Error ? reason.message : '报告详情读取失败');
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingReport(false);
      });
    return () => { cancelled = true; };
  }, [selectedId, sessionId]);

  const selectedIndex = items.find((item) => item.report_id === selectedId) ?? null;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {error ? (
        <div className="flex items-center justify-between gap-3 border border-t-down/30 bg-t-down/10 px-4 py-3 text-xs text-t-down">
          <span>{error}</span>
          <button type="button" onClick={refresh} className="inline-flex items-center gap-1"><RefreshCw size={13} />重试</button>
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 overflow-hidden border border-t-border bg-t-surface lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="min-h-0 overflow-y-auto border-r border-t-border max-lg:max-h-72 max-lg:border-b max-lg:border-r-0">
          {loadingList ? (
            <div className="flex min-h-40 items-center justify-center gap-2 text-xs text-t-text3"><RefreshCw size={14} className="animate-spin" />读取报告历史...</div>
          ) : items.length === 0 ? (
            <div className="flex min-h-40 flex-col items-center justify-center px-6 text-center text-xs text-t-text3">
              <FileText size={20} className="mb-2" />
              尚无报告历史，请在对话中生成研究报告。
            </div>
          ) : items.map((item) => (
            <button
              key={item.report_id}
              type="button"
              onClick={() => setSelectedId(item.report_id)}
              className={`w-full border-b border-t-border px-4 py-3 text-left transition-colors last:border-b-0 ${item.report_id === selectedId ? 'bg-t-accent/10' : 'hover:bg-t-hover'}`}
              data-testid="report-history-item"
            >
              <div className="line-clamp-2 text-sm font-medium leading-5 text-t-text">{item.title || item.ticker || '未命名报告'}</div>
              <div className="mt-2 flex items-center justify-between gap-3 text-2xs text-t-text3">
                <span>{item.ticker || '--'}</span>
                <span>{formatDateTime(item.generated_at || item.created_at)}</span>
              </div>
              {item.summary ? <div className="mt-2 line-clamp-2 text-xs leading-5 text-t-text2">{item.summary}</div> : null}
            </button>
          ))}
        </div>

        <div className="min-h-0 overflow-y-auto">
          {loadingReport ? (
            <div className="flex min-h-56 items-center justify-center gap-2 text-xs text-t-text3"><RefreshCw size={14} className="animate-spin" />回放报告...</div>
          ) : report ? (
            <div className="px-5 py-4 max-sm:px-3">
              <div className="mb-4 flex flex-wrap items-center justify-end gap-2 border-b border-t-border pb-3">
                {selectedIndex?.ticker ? (
                  <button
                    type="button"
                    onClick={() => navigate(`/dashboard/${encodeURIComponent(selectedIndex.ticker || '')}`)}
                    className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-t-border px-3 text-xs text-t-text2 hover:border-t-accent/50 hover:text-t-text"
                  >
                    <BarChart3 size={13} /> 打开看板
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => navigate(`/chat?report_id=${encodeURIComponent(report.report_id)}`)}
                  className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-t-accent/40 bg-t-accent/10 px-3 text-xs text-t-accent"
                >
                  <MessageSquare size={13} /> 进入对话
                </button>
              </div>
              <ReportView report={report} readOnly />
            </div>
          ) : (
            <div className="flex min-h-56 items-center justify-center text-sm text-t-text3">选择一份报告查看回放</div>
          )}
        </div>
      </div>
    </div>
  );
}

export function HistoryPage() {
  const [searchParams] = useSearchParams();
  const reportId = searchParams.get('report')?.trim() || null;
  const [tab, setTab] = useState<HistoryTab>(reportId ? 'reports' : 'predictions');

  useEffect(() => {
    if (reportId) setTab('reports');
  }, [reportId]);

  return (
    <main className="flex h-full min-h-0 flex-col bg-t-bg" data-testid="history-page">
      <header className="shrink-0 border-b border-t-border bg-t-surface px-5 py-4 max-sm:px-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <History size={18} className="text-t-accent" />
              <h1 className="text-base font-semibold text-t-text">历史</h1>
            </div>
            <p className="mt-1 text-xs text-t-text3">Prediction、Outcome 与研究报告的持久化记录</p>
          </div>
          <div className="inline-flex border border-t-border bg-t-bg p-1" role="tablist" aria-label="历史视图">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'predictions'}
              onClick={() => setTab('predictions')}
              className={`inline-flex min-h-8 items-center gap-1.5 px-3 text-xs ${tab === 'predictions' ? 'bg-t-accent/15 text-t-accent' : 'text-t-text3 hover:text-t-text'}`}
            >
              <Target size={13} /> Predictions
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'reports'}
              onClick={() => setTab('reports')}
              className={`inline-flex min-h-8 items-center gap-1.5 px-3 text-xs ${tab === 'reports' ? 'bg-t-accent/15 text-t-accent' : 'text-t-text3 hover:text-t-text'}`}
            >
              <FileText size={13} /> Reports
            </button>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-5 max-sm:p-3">
        <div className="mb-3 flex shrink-0 items-center gap-2 text-2xs text-t-text3">
          {tab === 'predictions' ? <Database size={12} /> : <CalendarClock size={12} />}
          {tab === 'predictions' ? '统计窗口：最近 90 天' : '按生成时间倒序'}
        </div>
        {tab === 'predictions' ? <PredictionHistoryPanel /> : <ReportsHistoryPanel initialReportId={reportId} />}
      </div>
    </main>
  );
}

export default HistoryPage;

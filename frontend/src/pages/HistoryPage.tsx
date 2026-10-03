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
import { formatPercentagePoints, formatRatioPercent } from './historyFormatting';
import { getPredictionDirectionPresentation } from '../utils/predictionPresentation';

type HistoryTab = 'predictions' | 'reports';

const DIRECTION_CLASSES = {
  long: 'bg-t-up/10 text-t-up',
  short: 'bg-t-down/10 text-t-down',
  neutral: 'bg-t-hover text-t-text2',
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

function resolveBucket(
  buckets: Record<string, PredictionStatBucket> | undefined,
  key: string,
): PredictionStatBucket | null {
  return buckets?.[key] ?? null;
}

function StatCell({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="min-w-0 px-1 py-2 sm:px-4">
      <div className="text-xs font-medium text-t-text2">{label}</div>
      <div className="mt-1.5 text-2xl font-semibold tabular-nums text-t-text">{value}</div>
      {detail ? <div className="mt-1 text-xs leading-5 text-t-text3">{detail}</div> : null}
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
      aria-pressed={active}
      className={`w-full border-l-[3px] px-4 py-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-t-accent ${
        active ? 'border-l-t-accent bg-t-accent/[0.07]' : 'border-l-transparent hover:bg-t-hover'
      }`}
      data-testid="prediction-history-item"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-base font-semibold text-t-text">{prediction.symbol}</span>
        <span className={`rounded px-2 py-1 text-xs font-medium ${DIRECTION_CLASSES[prediction.direction]}`}>
          {getPredictionDirectionPresentation(prediction.direction, status).label}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-t-text3">
        <span>{formatDateTime(prediction.created_at)}</span>
        <span className="text-t-text2">{OUTCOME_LABELS[status] || status}</span>
      </div>
      <div className="mt-2 line-clamp-2 text-sm leading-6 text-t-text2">{prediction.thesis}</div>
    </button>
  );
}

function PredictionDetail({ item }: { item: PredictionHistoryItem | null }) {
  const navigate = useNavigate();
  const prediction = item?.prediction ?? null;
  const outcome = item?.outcome ?? null;
  const run = usePredictionRun(prediction?.run_id);

  if (!prediction) {
    return <div className="flex min-h-56 items-center justify-center px-6 text-center text-sm text-t-text2 lg:h-full">选择一条 AI 判断查看详情</div>;
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
    <div className="mx-auto w-full min-w-0 max-w-5xl px-5 py-6 sm:px-7 lg:min-h-0 lg:overflow-y-auto" data-testid="prediction-history-detail">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold text-t-text">{prediction.symbol}</h2>
            <span className={`rounded px-2 py-1 text-xs font-medium ${DIRECTION_CLASSES[prediction.direction]}`}>
              {getPredictionDirectionPresentation(prediction.direction, status).label}
            </span>
            <span className="text-sm text-t-text2">
              {OUTCOME_LABELS[status] || status}
            </span>
          </div>
          <div className="mt-2 text-xs text-t-text3">创建于 {formatDateTime(prediction.created_at)}</div>
        </div>
        <button
          type="button"
          onClick={() => navigate(`/dashboard/${encodeURIComponent(prediction.symbol)}?analysis=prediction&predictionId=${encodeURIComponent(prediction.prediction_id)}`)}
          className="inline-flex min-h-10 items-center gap-2 rounded-md bg-t-hover px-3 text-sm text-t-text2 transition-colors hover:text-t-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent"
        >
          打开看板 <ArrowRight size={15} />
        </button>
      </div>

      <p className="mt-5 max-w-3xl break-words text-[15px] leading-7 text-t-text">{prediction.thesis}</p>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-t-text2">{getPredictionDirectionPresentation(prediction.direction, status).description}</p>
      <p className="mt-2 text-xs leading-5 text-t-text3">{getPredictionDirectionPresentation(prediction.direction, status).historical ? '本条判断已结束，展示原判断与复盘结果。' : '未结算的条件假设，需结合入场与失效条件核对。'}</p>

      <div className="mt-6 grid grid-cols-2 gap-x-4 gap-y-4 border-y border-t-divider py-5 sm:grid-cols-5">
        {levels.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <div className="text-xs font-medium text-t-text2">{label}</div>
            <div className="mt-2 text-lg font-semibold tabular-nums text-t-text">{formatPrice(value)}</div>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-7 xl:grid-cols-2">
        <section>
          <h3 className="text-sm font-semibold text-t-text">判断结果</h3>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-t-text3">结果</dt><dd className="text-right text-t-text2">{OUTCOME_LABELS[status] || status}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-t-text3">锚点后变动</dt><dd className={`text-right font-medium tabular-nums ${typeof outcome?.pct_since_anchor === 'number' && outcome.pct_since_anchor !== 0 ? outcome.pct_since_anchor > 0 ? 'text-t-up' : 'text-t-down' : 'text-t-text2'}`}>{formatPercentagePoints(outcome?.pct_since_anchor)}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-t-text3">评估至</dt><dd className="text-right text-t-text2">{formatDateTime(outcome?.evaluated_through)}</dd></div>
            <div className="flex justify-between gap-4"><dt className="shrink-0 text-t-text3">评估版本</dt><dd className="min-w-0 break-words text-right text-t-text2">{outcome?.algorithm_version || '--'}</dd></div>
          </dl>
        </section>
        <section>
          <h3 className="text-sm font-semibold text-t-text">数据与模型</h3>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="shrink-0 text-t-text3">行情来源</dt><dd className="min-w-0 break-words text-right text-t-text2">{prediction.evidence_provider || run?.market_provider || '--'}</dd></div>
            <div className="flex justify-between gap-4"><dt className="shrink-0 text-t-text3">证据时间</dt><dd className="min-w-0 text-right text-t-text2">{formatDateTime(prediction.evidence_as_of || run?.market_as_of)}</dd></div>
            <div className="flex justify-between gap-4"><dt className="shrink-0 text-t-text3">模型</dt><dd className="min-w-0 break-words text-right text-t-text2">{run?.llm_provider && run.llm_model ? `${run.llm_provider} / ${run.llm_model}` : '--'}</dd></div>
            <div className="flex justify-between gap-4"><dt className="shrink-0 text-t-text3">提示词版本</dt><dd className="min-w-0 break-words text-right text-t-text2">{prediction.prompt_version}</dd></div>
          </dl>
        </section>
      </div>

      {prediction.scenarios.length > 0 ? (
        <section className="mt-7 border-t border-t-divider pt-6">
          <h3 className="text-sm font-semibold text-t-text">情景与失效条件</h3>
          <div className="mt-4 space-y-5">
            {prediction.scenarios.map((scenario) => (
              <div key={`${scenario.name}-${scenario.probability}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 text-sm">
                <div className="min-w-0">
                  <div className="break-words font-medium text-t-text">{scenario.name}</div>
                  <div className="mt-1.5 max-w-3xl break-words leading-6 text-t-text2">失效条件：{scenario.invalidation}</div>
                </div>
                <div className="tabular-nums text-t-text2" aria-label={`情景概率 ${formatPercentagePoints(scenario.probability)}`}>{formatPercentagePoints(scenario.probability)}</div>
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
    () => items.find((item) => item.prediction.prediction_id === selectedId) ?? items[0] ?? null,
    [items, selectedId],
  );
  const aiBucket = resolveBucket(stats?.by_source, 'ai');
  const predictionStats = aiBucket ?? stats;

  return (
    <div className="flex shrink-0 flex-col gap-5 lg:min-h-0 lg:flex-1">
      <div className="grid shrink-0 grid-cols-2 gap-x-4 border-b border-t-divider pb-4 sm:grid-cols-4">
        <StatCell label="90 天 AI 判断" value={predictionStats ? String(predictionStats.predictions) : '--'} />
        <StatCell label="已结算" value={predictionStats ? String(predictionStats.resolved) : '--'} />
        <StatCell label="命中率" value={formatRatioPercent(predictionStats?.hit_rate)} detail={predictionStats ? predictionStats.resolved ? `${predictionStats.hits} 命中 · ${predictionStats.misses} 未命中` : '暂无已结算样本' : undefined} />
        <StatCell label="已失效" value={predictionStats ? String(predictionStats.invalidated) : '--'} />
      </div>

      {failure ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-t-down/10 px-4 py-3 text-sm text-t-down" role="alert">
          <span className="min-w-0 break-words">{failure.message}</span>
          <button type="button" onClick={refresh} className="inline-flex min-h-9 shrink-0 items-center gap-2"><RefreshCw size={15} />重试</button>
        </div>
      ) : null}

      <div className="grid bg-t-surface lg:min-h-0 lg:flex-1 lg:grid-cols-[320px_minmax(0,1fr)] lg:overflow-hidden xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className="overflow-y-auto border-t-divider max-lg:max-h-80 max-lg:border-b lg:min-h-0 lg:border-r">
          {loading ? (
            <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-t-text2"><RefreshCw size={16} className="animate-spin" />正在读取判断记录...</div>
          ) : items.length === 0 ? (
            <div className="flex min-h-48 flex-col items-center justify-center gap-3 px-6 text-center text-sm text-t-text2">
              <Target size={24} className="text-t-text3" />
              暂无 AI 判断记录
            </div>
          ) : items.map((item) => (
            <PredictionListItem
              key={item.prediction.prediction_id}
              item={item}
              active={item.prediction.prediction_id === selected?.prediction.prediction_id}
              onSelect={() => setSelectedId(item.prediction.prediction_id)}
            />
          ))}
        </div>
        <PredictionDetail key={selected?.prediction.prediction_id ?? 'empty'} item={selected} />
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
    <div className="flex shrink-0 flex-col gap-5 lg:min-h-0 lg:flex-1">
      {error ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-t-down/10 px-4 py-3 text-sm text-t-down" role="alert">
          <span className="min-w-0 break-words">{error}</span>
          <button type="button" onClick={refresh} className="inline-flex min-h-9 shrink-0 items-center gap-2"><RefreshCw size={15} />重试</button>
        </div>
      ) : null}

      <div className="grid bg-t-surface lg:min-h-0 lg:flex-1 lg:grid-cols-[320px_minmax(0,1fr)] lg:overflow-hidden xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className="overflow-y-auto border-t-divider max-lg:max-h-80 max-lg:border-b lg:min-h-0 lg:border-r">
          {loadingList ? (
            <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-t-text2"><RefreshCw size={16} className="animate-spin" />正在读取报告记录...</div>
          ) : items.length === 0 ? (
            <div className="flex min-h-48 flex-col items-center justify-center gap-3 px-6 text-center text-sm text-t-text2">
              <FileText size={24} className="text-t-text3" />
              暂无研究报告
            </div>
          ) : items.map((item) => (
            <button
              key={item.report_id}
              type="button"
              onClick={() => setSelectedId(item.report_id)}
              aria-pressed={item.report_id === selectedId}
              className={`w-full border-l-[3px] px-4 py-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-t-accent ${item.report_id === selectedId ? 'border-l-t-accent bg-t-accent/[0.07]' : 'border-l-transparent hover:bg-t-hover'}`}
              data-testid="report-history-item"
            >
              <div className="line-clamp-2 text-[15px] font-medium leading-6 text-t-text">{item.title || item.ticker || '未命名报告'}</div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-t-text3">
                <span>{item.ticker || '--'}</span>
                <span>{formatDateTime(item.generated_at || item.created_at)}</span>
              </div>
              {item.summary ? <div className="mt-2 line-clamp-2 text-sm leading-6 text-t-text2">{item.summary}</div> : null}
            </button>
          ))}
        </div>

        <div key={selectedId ?? 'empty'} className="min-w-0 lg:min-h-0 lg:overflow-y-auto">
          {loadingReport ? (
            <div className="flex min-h-56 items-center justify-center gap-2 text-sm text-t-text2"><RefreshCw size={16} className="animate-spin" />正在读取报告...</div>
          ) : report ? (
            <div className="mx-auto max-w-5xl px-5 py-6 sm:px-7">
              <div className="mb-5 flex flex-wrap items-center justify-end gap-2 border-b border-t-divider pb-4">
                {selectedIndex?.ticker ? (
                  <button
                    type="button"
                    onClick={() => navigate(`/dashboard/${encodeURIComponent(selectedIndex.ticker || '')}`)}
                    className="inline-flex min-h-10 items-center gap-2 rounded-md bg-t-hover px-3 text-sm text-t-text2 hover:text-t-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent"
                  >
                    <BarChart3 size={15} /> 打开看板
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => navigate(`/chat?report_id=${encodeURIComponent(report.report_id)}`)}
                  className="inline-flex min-h-10 items-center gap-2 rounded-md bg-t-accent/10 px-3 text-sm text-t-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent"
                >
                  <MessageSquare size={15} /> 进入对话
                </button>
              </div>
              <ReportView report={report} readOnly />
            </div>
          ) : (
            <div className="flex min-h-56 items-center justify-center text-sm text-t-text2">选择一份报告查看详情</div>
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
      <header className="shrink-0 border-b border-t-divider bg-t-surface px-5 py-5 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <History size={20} className="text-t-text2" />
              <h1 className="text-xl font-semibold text-t-text">历史记录</h1>
            </div>
          </div>
          <div className="inline-flex rounded-md bg-t-bg p-1" role="tablist" aria-label="历史视图">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'predictions'}
              onClick={() => setTab('predictions')}
              className={`inline-flex min-h-9 items-center gap-2 rounded px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent ${tab === 'predictions' ? 'bg-t-hover font-medium text-t-text' : 'text-t-text2 hover:text-t-text'}`}
            >
              <Target size={15} /> AI 判断
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'reports'}
              onClick={() => setTab('reports')}
              className={`inline-flex min-h-9 items-center gap-2 rounded px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-t-accent ${tab === 'reports' ? 'bg-t-hover font-medium text-t-text' : 'text-t-text2 hover:text-t-text'}`}
            >
              <FileText size={15} /> 研究报告
            </button>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mb-3 flex shrink-0 items-center gap-2 text-xs text-t-text2">
          {tab === 'predictions' ? <Database size={14} /> : <CalendarClock size={14} />}
          {tab === 'predictions' ? '最近 90 天' : '最近生成'}
        </div>
        {tab === 'predictions' ? <PredictionHistoryPanel /> : <ReportsHistoryPanel initialReportId={reportId} />}
      </div>
    </main>
  );
}

export default HistoryPage;

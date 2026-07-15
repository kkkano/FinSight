import {
  AlertCircle,
  Clock3,
  Database,
  MessageCircleQuestion,
  Minus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

import type {
  PredictionFailure,
  PredictionRunView,
} from '../../api/domains/predictions';
import type { PredictionOverlayLoadState } from '../../hooks/usePredictionOverlay';
import type { PredictionEligibility } from '../../hooks/usePredictionEligibility';

type PredictionTrackProps = {
  authenticated: boolean;
  eligibility: PredictionEligibility;
  loadState: PredictionOverlayLoadState;
  generationPhase: 'idle' | 'submitting' | 'polling' | 'succeeded' | 'failed' | 'timed_out';
  generationRun: PredictionRunView | null;
  generationFailure: PredictionFailure | null;
  isGenerating: boolean;
  onGenerate: () => void;
  onAsk: () => void;
};

const DIRECTION = {
  long: {
    label: 'LONG',
    text: '偏多',
    Icon: TrendingUp,
    className: 'border-t-up/40 bg-t-up/10 text-t-up',
  },
  short: {
    label: 'SHORT',
    text: '偏空',
    Icon: TrendingDown,
    className: 'border-t-down/40 bg-t-down/10 text-t-down',
  },
  neutral: {
    label: 'NEUTRAL',
    text: '中性',
    Icon: Minus,
    className: 'border-t-text3/40 bg-t-hover text-t-text2',
  },
} as const;

const STATUS_LABELS: Record<string, string> = {
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

function formatPrice(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '--';
}

function formatConfidence(value: number): string {
  const normalized = value <= 1 ? value * 100 : value;
  return `${Math.max(0, Math.min(100, normalized)).toFixed(0)}%`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function PriceLevel({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="min-w-0 border-l border-t-border pl-3 first:border-l-0 first:pl-0">
      <div className="text-2xs text-t-text3">{label}</div>
      <div className="mt-1 text-sm font-semibold tabular-nums text-t-text" data-testid="prediction-price-level-value">
        {formatPrice(value)}
      </div>
    </div>
  );
}

export function PredictionTrack({
  authenticated,
  eligibility,
  loadState,
  generationPhase,
  generationRun,
  generationFailure,
  isGenerating,
  onGenerate,
  onAsk,
}: PredictionTrackProps) {
  const prediction = loadState.status === 'ready' ? loadState.response.prediction : null;
  const outcome = loadState.status === 'ready' ? loadState.response.outcome : null;
  const run = generationRun?.status === 'succeeded' ? generationRun : loadState.run;
  const canGenerate = authenticated && eligibility.status === 'trusted' && !isGenerating;
  const direction = prediction ? DIRECTION[prediction.direction] : null;

  const generationMessage = generationPhase === 'submitting'
    ? '正在创建生成任务...'
    : generationPhase === 'polling'
      ? generationRun?.status === 'queued' ? '任务已排队，等待分析...' : '正在读取证据并生成判断...'
      : generationFailure?.message ?? null;

  const emptyMessage = !authenticated
    ? '登录后才能生成和读取个人 AI 判断。'
    : eligibility.status === 'checking'
      ? '正在校验行情来源...'
      : eligibility.status === 'degraded' || eligibility.status === 'unavailable'
        ? eligibility.reason
        : loadState.status === 'loading'
          ? '正在读取最近一次判断...'
          : loadState.status === 'not_found'
            ? '尚未生成 AI 判断。'
            : loadState.failure?.message ?? '尚未生成 AI 判断。';

  const generateLabel = prediction ? '刷新判断' : '生成 AI 判断';

  return (
    <section
      data-testid="prediction-track"
      className="shrink-0 border-y border-t-border bg-t-surface px-5 py-3 max-lg:px-3"
      aria-label="AI Prediction 价格轨道"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 max-sm:basis-full">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-t-text">
              <Sparkles size={14} className="text-t-predict" />
              AI 判断
            </span>
            <span className="rounded border border-t-predict/35 bg-t-predict/10 px-1.5 py-0.5 text-2xs text-t-predict">
              PREDICTION
            </span>
            {direction && (
              <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-semibold ${direction.className}`}>
                <direction.Icon size={11} />
                {direction.label} · {direction.text}
              </span>
            )}
            {prediction && (
              <span className="text-2xs text-t-text3">
                置信度 {formatConfidence(prediction.confidence)} · {STATUS_LABELS[outcome?.status || prediction.status] || outcome?.status || prediction.status}
              </span>
            )}
          </div>

          {prediction ? (
            <>
              <p className="mt-2 max-w-5xl text-xs leading-5 text-t-text2">{prediction.thesis}</p>
              <div className="mt-3 grid grid-cols-2 gap-y-3 sm:grid-cols-5">
                <PriceLevel label="锚点" value={prediction.anchor.price} />
                <PriceLevel label="入场" value={prediction.entry} />
                <PriceLevel label="止损" value={prediction.stop} />
                <PriceLevel label="目标 1" value={prediction.target1} />
                <PriceLevel label="目标 2" value={prediction.target2} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-t-text3">
                <span className="inline-flex items-center gap-1">
                  <Database size={11} />
                  行情 {prediction.evidence_provider || eligibility.provider || '--'}
                </span>
                <span className="inline-flex items-center gap-1">
                  <Clock3 size={11} />
                  证据 {formatDateTime(prediction.evidence_as_of || eligibility.asOf)}
                </span>
                <span>模型 {run?.llm_provider && run?.llm_model ? `${run.llm_provider} / ${run.llm_model}` : '--'}</span>
                <span>Prompt {prediction.prompt_version}</span>
              </div>
            </>
          ) : (
            <div className="mt-2 flex items-start gap-2 text-xs text-t-text2" data-testid="prediction-empty-state">
              {eligibility.status === 'trusted' ? (
                <ShieldCheck size={14} className="mt-0.5 shrink-0 text-t-up" />
              ) : (
                <AlertCircle size={14} className="mt-0.5 shrink-0 text-t-warning" />
              )}
              <span>{generationMessage || emptyMessage}</span>
            </div>
          )}

          {prediction && generationMessage && (
            <div className={`mt-2 text-2xs ${generationFailure ? 'text-t-warning' : 'text-t-predict'}`}>
              {generationMessage}
              {generationFailure ? ` [${generationFailure.code}]` : ''}
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2 max-sm:w-full">
          <button
            type="button"
            data-testid="prediction-generate"
            onClick={onGenerate}
            disabled={!canGenerate}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-t-predict/45 bg-t-predict/10 px-3 text-xs font-medium text-t-predict transition-colors hover:bg-t-predict/15 disabled:cursor-not-allowed disabled:opacity-45 max-sm:flex-1 max-sm:justify-center"
            title={!authenticated ? '登录后才能生成' : eligibility.reason || generateLabel}
          >
            <RefreshCw size={14} className={isGenerating ? 'animate-spin' : ''} />
            {isGenerating ? '生成中' : generateLabel}
          </button>
          <button
            type="button"
            onClick={onAsk}
            disabled={!authenticated}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-t-border px-3 text-xs text-t-text2 transition-colors hover:border-t-accent/50 hover:text-t-text disabled:opacity-45 max-sm:flex-1 max-sm:justify-center"
            title="带当前标的和判断进入对话"
          >
            <MessageCircleQuestion size={14} />
            追问
          </button>
        </div>
      </div>
    </section>
  );
}

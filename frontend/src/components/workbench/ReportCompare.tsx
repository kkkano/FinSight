import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft, ArrowDown, ArrowUp, Minus,
  Loader2, AlertTriangle, ShieldAlert, ShieldCheck,
  Calendar,
} from 'lucide-react';

import { apiClient } from '../../api/client';
import { useStore } from '../../store/useStore';
import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CompareResult {
  report_a: { report_id: string; title?: string | null; generated_at?: string | null };
  report_b: { report_id: string; title?: string | null; generated_at?: string | null };
  diff: {
    confidence_score: { a: number | null; b: number | null; delta: number | null };
    sentiment: { a: string | null; b: string | null; changed: boolean };
    risks: { added: string[]; removed: string[]; unchanged_count: number };
    summary: { a: string | null; b: string | null };
  };
}

interface ReportCompareProps {
  reportId1: string;
  reportId2: string;
  onClose: () => void;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '--';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return '--';
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hour = String(d.getHours()).padStart(2, '0');
  const min = String(d.getMinutes()).padStart(2, '0');
  return `${month}-${day} ${hour}:${min}`;
}

function DeltaIndicator({ value }: { value: number | null }) {
  if (value === null || value === 0) {
    return <Minus size={12} className="text-fin-muted" />;
  }
  if (value > 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-fin-success text-2xs font-medium">
        <ArrowUp size={10} />
        +{(value * 100).toFixed(1)}%
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-fin-danger text-2xs font-medium">
      <ArrowDown size={10} />
      {(value * 100).toFixed(1)}%
    </span>
  );
}

function SentimentBadge({ sentiment }: { sentiment: string | null }) {
  if (!sentiment) return <span className="text-fin-muted text-2xs">--</span>;
  const variant = sentiment === 'bullish' ? 'success' : sentiment === 'bearish' ? 'danger' : 'default';
  const label = sentiment === 'bullish' ? '看涨' : sentiment === 'bearish' ? '看跌' : '中性';
  return <Badge variant={variant}>{label}</Badge>;
}

function ScoreDisplay({ score, label }: { score: number | null; label: string }) {
  const pct = score !== null ? Math.round(score * 100) : null;
  return (
    <div className="text-center">
      <div className="text-2xs text-fin-muted mb-1">{label}</div>
      <div
        className={`text-lg font-bold ${
          pct !== null && pct >= 70
            ? 'text-fin-success'
            : pct !== null && pct < 40
              ? 'text-fin-danger'
              : 'text-fin-text'
        }`}
      >
        {pct !== null ? `${pct}%` : '--'}
      </div>
    </div>
  );
}

/** Simple word-level diff highlight for short summaries. */
function DiffSummary({ textA, textB }: { textA: string; textB: string }) {
  const wordsA = useMemo(() => new Set(textA.split(/\s+/).filter(Boolean)), [textA]);
  const wordsB = useMemo(() => new Set(textB.split(/\s+/).filter(Boolean)), [textB]);

  const renderHighlighted = (text: string, otherWords: Set<string>) => {
    if (!text) return <span className="text-fin-muted">暂无摘要</span>;
    const tokens = text.split(/(\s+)/);
    return tokens.map((token, i) => {
      const isWhitespace = /^\s+$/.test(token);
      if (isWhitespace) return <span key={`ws-${String(i)}`}>{token}</span>;
      const isUnique = !otherWords.has(token);
      return (
        <span
          key={`t-${String(i)}`}
          className={isUnique ? 'bg-amber-500/15 rounded px-0.5' : ''}
        >
          {token}
        </span>
      );
    });
  };

  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <div className="text-2xs text-fin-muted mb-1">报告 A</div>
        <div className="text-2xs text-fin-text leading-relaxed line-clamp-5">
          {renderHighlighted(textA, wordsB)}
        </div>
      </div>
      <div>
        <div className="text-2xs text-fin-muted mb-1">报告 B</div>
        <div className="text-2xs text-fin-text leading-relaxed line-clamp-5">
          {renderHighlighted(textB, wordsA)}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ReportCompare                                                      */
/* ------------------------------------------------------------------ */

function ReportCompare({ reportId1, reportId2, onClose }: ReportCompareProps) {
  const sessionId = useStore((s) => s.sessionId);
  const [data, setData] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const isSameReport = reportId1 === reportId2;

  useEffect(() => {
    if (isSameReport) {
      setLoading(false);
      setError('请选择两份不同的报告进行对比');
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    apiClient
      .compareReports({
        sessionId,
        reportId1,
        reportId2,
        includeBlocked: true,
      })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message =
            err instanceof Error ? err.message : '对比加载失败';
          setError(message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [sessionId, reportId1, reportId2, isSameReport]);

  const diff = data?.diff ?? null;
  const reportA = data?.report_a;
  const reportB = data?.report_b;

  const labelA = reportA?.title || reportId1.slice(0, 12) + '...';
  const labelB = reportB?.title || reportId2.slice(0, 12) + '...';

  return (
    <Card className="p-4">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded hover:bg-fin-hover text-fin-muted hover:text-fin-text transition-colors"
          aria-label="返回"
        >
          <ArrowLeft size={16} />
        </button>
        <span className="text-sm font-semibold text-fin-text">报告对比</span>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center gap-2 py-8 text-fin-muted text-xs">
          <Loader2 size={16} className="animate-spin" />
          加载对比数据...
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="flex items-center gap-2 py-4 text-xs text-red-500">
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {/* Content */}
      {diff && !loading && (
        <div className="space-y-4">
          {/* Report meta headers */}
          <div className="grid grid-cols-2 gap-3">
            <div className="p-2 rounded-lg bg-fin-bg-secondary">
              <div className="text-2xs text-fin-muted mb-0.5 font-medium">报告 A</div>
              <div className="text-xs text-fin-text font-medium truncate" title={labelA}>
                {labelA}
              </div>
              {reportA?.generated_at && (
                <div className="flex items-center gap-1 text-2xs text-fin-muted mt-0.5">
                  <Calendar size={10} />
                  {formatDateTime(reportA.generated_at)}
                </div>
              )}
            </div>
            <div className="p-2 rounded-lg bg-fin-bg-secondary">
              <div className="text-2xs text-fin-muted mb-0.5 font-medium">报告 B</div>
              <div className="text-xs text-fin-text font-medium truncate" title={labelB}>
                {labelB}
              </div>
              {reportB?.generated_at && (
                <div className="flex items-center gap-1 text-2xs text-fin-muted mt-0.5">
                  <Calendar size={10} />
                  {formatDateTime(reportB.generated_at)}
                </div>
              )}
            </div>
          </div>

          {/* Confidence Score */}
          <div className="p-3 rounded-lg bg-fin-bg-secondary">
            <div className="text-2xs text-fin-muted mb-2 font-medium">置信度对比</div>
            <div className="grid grid-cols-3 items-center">
              <ScoreDisplay score={diff.confidence_score.a} label="报告 A" />
              <div className="flex flex-col items-center gap-1">
                <div className="text-2xs text-fin-muted">变化</div>
                <DeltaIndicator value={diff.confidence_score.delta} />
              </div>
              <ScoreDisplay score={diff.confidence_score.b} label="报告 B" />
            </div>
          </div>

          {/* Sentiment */}
          <div className="p-3 rounded-lg bg-fin-bg-secondary">
            <div className="text-2xs text-fin-muted mb-2 font-medium">情绪判断</div>
            <div className="grid grid-cols-3 items-center text-center">
              <div>
                <div className="text-2xs text-fin-muted mb-1">报告 A</div>
                <SentimentBadge sentiment={diff.sentiment.a} />
              </div>
              <div>
                {diff.sentiment.changed ? (
                  <Badge variant="warning">已变化</Badge>
                ) : (
                  <Badge variant="default">未变化</Badge>
                )}
              </div>
              <div>
                <div className="text-2xs text-fin-muted mb-1">报告 B</div>
                <SentimentBadge sentiment={diff.sentiment.b} />
              </div>
            </div>
          </div>

          {/* Risks */}
          <div className="p-3 rounded-lg bg-fin-bg-secondary">
            <div className="text-2xs text-fin-muted mb-2 font-medium">风险变化</div>
            <div className="text-2xs text-fin-muted mb-2">
              不变风险: {diff.risks.unchanged_count} 个
            </div>

            {diff.risks.added.length > 0 && (
              <div className="mb-2">
                <div className="flex items-center gap-1 text-2xs text-fin-danger mb-1">
                  <ShieldAlert size={10} />
                  新增风险 ({diff.risks.added.length})
                </div>
                <ul className="space-y-0.5">
                  {diff.risks.added.map((risk, i) => (
                    <li key={`added-${String(i)}`} className="text-2xs text-fin-text pl-3 truncate">
                      • {risk}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {diff.risks.removed.length > 0 && (
              <div>
                <div className="flex items-center gap-1 text-2xs text-fin-success mb-1">
                  <ShieldCheck size={10} />
                  已消除风险 ({diff.risks.removed.length})
                </div>
                <ul className="space-y-0.5">
                  {diff.risks.removed.map((risk, i) => (
                    <li key={`removed-${String(i)}`} className="text-2xs text-fin-text pl-3 truncate">
                      • {risk}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {diff.risks.added.length === 0 && diff.risks.removed.length === 0 && (
              <div className="text-2xs text-fin-muted">风险评估无变化</div>
            )}
          </div>

          {/* Summary comparison with diff highlight */}
          <div className="p-3 rounded-lg bg-fin-bg-secondary">
            <div className="text-2xs text-fin-muted mb-2 font-medium">摘要对比</div>
            <DiffSummary
              textA={diff.summary.a || ''}
              textB={diff.summary.b || ''}
            />
          </div>
        </div>
      )}
    </Card>
  );
}

export { ReportCompare };
export type { ReportCompareProps };

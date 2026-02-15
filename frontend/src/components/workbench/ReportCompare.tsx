import { useEffect, useState } from 'react';
import {
  ArrowLeft, ArrowDown, ArrowUp, Minus,
  Loader2, AlertTriangle, ShieldAlert, ShieldCheck,
} from 'lucide-react';

import { apiClient } from '../../api/client';
import { useStore } from '../../store/useStore';
import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CompareResult {
  confidence_score: { a: number | null; b: number | null; delta: number | null };
  sentiment: { a: string | null; b: string | null; changed: boolean };
  risks: { added: string[]; removed: string[]; unchanged_count: number };
  summary: { a: string | null; b: string | null };
}

interface ReportCompareProps {
  reportId1: string;
  reportId2: string;
  onClose: () => void;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

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
      <div className={`text-lg font-bold ${pct !== null && pct >= 70 ? 'text-fin-success' : pct !== null && pct < 40 ? 'text-fin-danger' : 'text-fin-text'}`}>
        {pct !== null ? `${pct}%` : '--'}
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

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    apiClient
      .compareReports({
        sessionId,
        reportId1,
        reportId2,
      })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '对比加载失败');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [sessionId, reportId1, reportId2]);

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
      {data && !loading && (
        <div className="space-y-4">
          {/* Report IDs */}
          <div className="grid grid-cols-2 gap-3 text-2xs text-fin-muted">
            <div className="truncate">
              <span className="text-fin-text-secondary font-medium">报告 A:</span>{' '}
              {reportId1.slice(0, 12)}...
            </div>
            <div className="truncate">
              <span className="text-fin-text-secondary font-medium">报告 B:</span>{' '}
              {reportId2.slice(0, 12)}...
            </div>
          </div>

          {/* Confidence Score */}
          <div className="p-3 rounded-lg bg-fin-bg-secondary">
            <div className="text-2xs text-fin-muted mb-2 font-medium">置信度对比</div>
            <div className="grid grid-cols-3 items-center">
              <ScoreDisplay score={data.confidence_score.a} label="报告 A" />
              <div className="flex flex-col items-center gap-1">
                <div className="text-2xs text-fin-muted">变化</div>
                <DeltaIndicator value={data.confidence_score.delta} />
              </div>
              <ScoreDisplay score={data.confidence_score.b} label="报告 B" />
            </div>
          </div>

          {/* Sentiment */}
          <div className="p-3 rounded-lg bg-fin-bg-secondary">
            <div className="text-2xs text-fin-muted mb-2 font-medium">情绪判断</div>
            <div className="grid grid-cols-3 items-center text-center">
              <div>
                <div className="text-2xs text-fin-muted mb-1">报告 A</div>
                <SentimentBadge sentiment={data.sentiment.a} />
              </div>
              <div>
                {data.sentiment.changed ? (
                  <Badge variant="warning">已变化</Badge>
                ) : (
                  <Badge variant="default">未变化</Badge>
                )}
              </div>
              <div>
                <div className="text-2xs text-fin-muted mb-1">报告 B</div>
                <SentimentBadge sentiment={data.sentiment.b} />
              </div>
            </div>
          </div>

          {/* Risks */}
          <div className="p-3 rounded-lg bg-fin-bg-secondary">
            <div className="text-2xs text-fin-muted mb-2 font-medium">风险变化</div>
            <div className="text-2xs text-fin-muted mb-2">
              不变风险: {data.risks.unchanged_count} 个
            </div>

            {data.risks.added.length > 0 && (
              <div className="mb-2">
                <div className="flex items-center gap-1 text-2xs text-fin-danger mb-1">
                  <ShieldAlert size={10} />
                  新增风险 ({data.risks.added.length})
                </div>
                <ul className="space-y-0.5">
                  {data.risks.added.map((risk, i) => (
                    <li key={`added-${String(i)}`} className="text-2xs text-fin-text pl-3 truncate">
                      • {risk}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {data.risks.removed.length > 0 && (
              <div>
                <div className="flex items-center gap-1 text-2xs text-fin-success mb-1">
                  <ShieldCheck size={10} />
                  已消除风险 ({data.risks.removed.length})
                </div>
                <ul className="space-y-0.5">
                  {data.risks.removed.map((risk, i) => (
                    <li key={`removed-${String(i)}`} className="text-2xs text-fin-text pl-3 truncate">
                      • {risk}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {data.risks.added.length === 0 && data.risks.removed.length === 0 && (
              <div className="text-2xs text-fin-muted">风险评估无变化</div>
            )}
          </div>

          {/* Summary comparison */}
          <div className="p-3 rounded-lg bg-fin-bg-secondary">
            <div className="text-2xs text-fin-muted mb-2 font-medium">摘要对比</div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-2xs text-fin-muted mb-1">报告 A</div>
                <div className="text-2xs text-fin-text leading-relaxed line-clamp-4">
                  {data.summary.a || '暂无摘要'}
                </div>
              </div>
              <div>
                <div className="text-2xs text-fin-muted mb-1">报告 B</div>
                <div className="text-2xs text-fin-text leading-relaxed line-clamp-4">
                  {data.summary.b || '暂无摘要'}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

export { ReportCompare };
export type { ReportCompareProps };

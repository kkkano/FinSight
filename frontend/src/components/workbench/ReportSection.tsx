import { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ChevronDown, ChevronRight, GitCompareArrows,
  Inbox, Library, Search,
} from 'lucide-react';

import type { ReportIndexItem } from '../../api/client';
import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';
import { Input } from '../ui/Input';
import { ReportCompare } from './ReportCompare';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type SortMode = 'date' | 'confidence';

interface ReportSectionProps {
  reports: ReportIndexItem[];
  loading: boolean;
  selectedReportId?: string | null;
  onSelectReport?: (reportId: string) => void;
}

interface DateGroup {
  label: string;
  key: string;
  items: ReportIndexItem[];
}

const MAX_VISIBLE = 12;

/* ------------------------------------------------------------------ */
/*  Date grouping helpers                                              */
/* ------------------------------------------------------------------ */

function toDateKey(dateStr: string | undefined): string {
  if (!dateStr) return 'unknown';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return 'unknown';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function classifyDateGroup(dateKey: string): string {
  if (dateKey === 'unknown') return 'earlier';
  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  if (dateKey === todayKey) return 'today';

  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const yesterdayKey = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`;

  if (dateKey === yesterdayKey) return 'yesterday';
  return 'earlier';
}

const GROUP_LABELS: Record<string, string> = {
  today: '今天',
  yesterday: '昨天',
  earlier: '更早',
};

const GROUP_ORDER: string[] = ['today', 'yesterday', 'earlier'];

function groupByDate(items: ReportIndexItem[]): DateGroup[] {
  const buckets: Record<string, ReportIndexItem[]> = {
    today: [],
    yesterday: [],
    earlier: [],
  };

  for (const item of items) {
    const dateStr = item.generated_at || item.created_at;
    const dateKey = toDateKey(dateStr);
    const group = classifyDateGroup(dateKey);
    buckets[group].push(item);
  }

  return GROUP_ORDER
    .filter((key) => buckets[key].length > 0)
    .map((key) => ({
      label: GROUP_LABELS[key],
      key,
      items: buckets[key],
    }));
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function ReportSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={`skeleton-${String(i)}`}
          className="p-2 rounded-lg border border-fin-border animate-pulse"
        >
          <div className="h-3.5 bg-fin-bg-secondary rounded w-3/4" />
          <div className="h-2.5 bg-fin-bg-secondary rounded w-1/2 mt-2" />
          <div className="flex gap-1 mt-2">
            <div className="h-4 w-10 bg-fin-bg-secondary rounded" />
            <div className="h-4 w-12 bg-fin-bg-secondary rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-6 text-fin-muted gap-2">
      <Inbox size={28} strokeWidth={1.5} />
      <span className="text-xs">暂无已收录研报</span>
    </div>
  );
}

function ConfidenceBadge({ score }: { score: number | undefined }) {
  if (typeof score !== 'number') return null;
  const pct = Math.round(score * 100);
  const variant = pct >= 70 ? 'success' : pct >= 40 ? 'warning' : 'danger';
  return <Badge variant={variant}>{pct}%</Badge>;
}

function formatTime(dateStr: string | undefined): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/* ------------------------------------------------------------------ */
/*  TimelineGroup                                                      */
/* ------------------------------------------------------------------ */

interface TimelineGroupProps {
  group: DateGroup;
  defaultExpanded: boolean;
  selectedReportId?: string | null;
  compareIds: Set<string>;
  compareMode: boolean;
  onToggleCompare: (id: string) => void;
  onViewReport: (reportId: string) => void;
}

function TimelineGroup({
  group,
  defaultExpanded,
  selectedReportId,
  compareIds,
  compareMode,
  onToggleCompare,
  onViewReport,
}: TimelineGroupProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center gap-1.5 w-full text-left py-1 text-xs font-medium text-fin-text-secondary hover:text-fin-text transition-colors"
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span>{group.label}</span>
        <span className="text-fin-muted">({group.items.length})</span>
      </button>

      {expanded && (
        <div className="ml-2 border-l border-fin-border pl-3 space-y-1.5 mt-1">
          {group.items.map((item) => {
            const isSelected = compareIds.has(item.report_id);
            const isPreviewActive = selectedReportId === item.report_id;

            return (
              <div
                key={item.report_id}
                className={`p-2 rounded-lg border transition-colors ${
                  isSelected
                    ? 'border-fin-primary/60 bg-fin-primary/5'
                    : isPreviewActive
                      ? 'border-fin-primary/40 bg-fin-primary/5'
                      : 'border-fin-border hover:border-fin-primary/30 hover:bg-fin-bg'
                }`}
              >
                <div className="flex items-start gap-2">
                  {/* Compare checkbox */}
                  {compareMode && (
                    <label className="flex items-center mt-0.5 cursor-pointer shrink-0">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => onToggleCompare(item.report_id)}
                        disabled={!isSelected && compareIds.size >= 2}
                        className="w-3.5 h-3.5 rounded border-fin-border text-fin-primary focus:ring-fin-primary/30 cursor-pointer disabled:opacity-40"
                      />
                    </label>
                  )}

                  {/* Content */}
                  <button
                    type="button"
                    onClick={() => onViewReport(item.report_id)}
                    className="flex-1 min-w-0 text-left"
                    data-testid={`workbench-report-item-${item.report_id}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-fin-text font-medium truncate flex-1">
                        {item.title || item.report_id}
                      </span>
                      <ConfidenceBadge score={item.confidence_score} />
                    </div>

                    <div className="text-2xs text-fin-muted mt-0.5 flex items-center gap-1.5">
                      {item.ticker && (
                        <span className="font-medium text-fin-text-secondary">{item.ticker}</span>
                      )}
                      <span>{formatTime(item.generated_at || item.created_at)}</span>
                      {item.summary && (
                        <span className="truncate max-w-[160px]">&middot; {item.summary}</span>
                      )}
                    </div>

                    <div className="mt-1 flex flex-wrap gap-1">
                      {item.ticker && (
                        <Badge variant="info" data-testid={`workbench-report-tag-ticker-${item.report_id}`}>
                          {item.ticker}
                        </Badge>
                      )}
                      {item.analysis_depth && (
                        <Badge
                          variant={item.analysis_depth === 'deep_research' ? 'warning' : 'default'}
                          data-testid={`workbench-report-tag-depth-${item.report_id}`}
                        >
                          {item.analysis_depth}
                        </Badge>
                      )}
                      {item.source_trigger && (
                        <Badge
                          variant="default"
                          data-testid={`workbench-report-tag-trigger-${item.report_id}`}
                        >
                          {item.source_trigger}
                        </Badge>
                      )}
                    </div>

                    {Array.isArray(item.tags) && item.tags.length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {item.tags.includes('compare') && <Badge variant="info">对比</Badge>}
                        {item.tags.includes('conflict') && <Badge variant="warning">冲突</Badge>}
                        {item.tags.includes('filing') && <Badge variant="success">Filing</Badge>}
                      </div>
                    )}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ReportSection (main)                                               */
/* ------------------------------------------------------------------ */

function ReportSection({ reports, loading, selectedReportId, onSelectReport }: ReportSectionProps) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('date');
  const [compareMode, setCompareMode] = useState(false);
  const [compareIds, setCompareIds] = useState<Set<string>>(new Set());
  const [showCompare, setShowCompare] = useState(false);

  /* ---- Filter + sort ---- */
  const filtered = useMemo(() => {
    const query = filter.trim().toLowerCase();
    const base = query
      ? reports.filter((item) => {
          const title = (item.title || '').toLowerCase();
          const ticker = (item.ticker || '').toLowerCase();
          const reportId = (item.report_id || '').toLowerCase();
          const analysisDepth = String(item.analysis_depth || '').toLowerCase();
          const sourceTrigger = String(item.source_trigger || '').toLowerCase();
          return (
            title.includes(query)
            || ticker.includes(query)
            || reportId.includes(query)
            || analysisDepth.includes(query)
            || sourceTrigger.includes(query)
          );
        })
      : reports;

    const sorted = [...base].sort((a, b) => {
      if (sortMode === 'confidence') {
        return (b.confidence_score ?? 0) - (a.confidence_score ?? 0);
      }
      const bDate = Date.parse(b.generated_at || b.created_at || '');
      const aDate = Date.parse(a.generated_at || a.created_at || '');
      if (!Number.isNaN(bDate) && !Number.isNaN(aDate)) return bDate - aDate;
      return 0;
    });

    return sorted.slice(0, MAX_VISIBLE);
  }, [reports, filter, sortMode]);

  /* ---- Date groups ---- */
  const groups = useMemo(() => groupByDate(filtered), [filtered]);

  /* ---- Compare toggle ---- */
  const handleToggleCompare = useCallback((id: string) => {
    setCompareIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < 2) {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleExitCompare = useCallback(() => {
    setCompareMode(false);
    setCompareIds(new Set());
    setShowCompare(false);
  }, []);

  const handleViewReport = useCallback(
    (reportId: string) => {
      if (typeof onSelectReport === 'function') {
        onSelectReport(reportId);
        return;
      }
      navigate(`/chat?report_id=${encodeURIComponent(reportId)}`);
    },
    [navigate, onSelectReport],
  );

  const compareArray = useMemo(() => Array.from(compareIds), [compareIds]);

  /* ---- Compare panel ---- */
  if (showCompare && compareArray.length === 2) {
    return (
      <ReportCompare
        reportId1={compareArray[0]}
        reportId2={compareArray[1]}
        onClose={handleExitCompare}
      />
    );
  }

  return (
    <Card className="p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-fin-text font-semibold text-sm">
          <Library size={16} className="text-fin-primary" />
          研报时间线
        </div>

        <button
          type="button"
          onClick={() => {
            if (compareMode) {
              handleExitCompare();
            } else {
              setCompareMode(true);
            }
          }}
          className={`flex items-center gap-1 px-2 py-1 rounded text-2xs transition-colors ${
            compareMode
              ? 'bg-fin-primary/10 text-fin-primary'
              : 'text-fin-muted hover:text-fin-text hover:bg-fin-hover'
          }`}
        >
          <GitCompareArrows size={12} />
          {compareMode ? '退出对比' : '对比'}
        </button>
      </div>

      {/* Filter & Sort */}
      <div className="flex items-center gap-2 mb-3">
        <div className="relative flex-1">
          <Search
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-fin-muted pointer-events-none"
          />
          <Input
            placeholder="搜索 Ticker / 标题..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="!pl-8 !py-1 !text-xs"
          />
        </div>
        <div className="relative">
          <select
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value as SortMode)}
            className="appearance-none bg-fin-bg border border-fin-border rounded-lg px-2.5 py-1.5 pr-7 text-xs text-fin-text cursor-pointer focus:outline-none focus:border-fin-primary focus:ring-1 focus:ring-fin-primary/30 transition-colors"
          >
            <option value="date">按日期</option>
            <option value="confidence">按置信度</option>
          </select>
          <ChevronDown
            size={12}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-fin-muted pointer-events-none"
          />
        </div>
      </div>

      {/* Compare action bar */}
      {compareMode && (
        <div className="flex items-center gap-2 mb-3 px-2 py-1.5 rounded-lg bg-fin-bg-secondary text-2xs text-fin-muted">
          <span>已选 {compareIds.size}/2 份报告</span>
          {compareIds.size === 2 && (
            <button
              type="button"
              onClick={() => setShowCompare(true)}
              className="ml-auto px-2 py-0.5 rounded bg-fin-primary text-white text-2xs hover:bg-fin-primary/90 transition-colors"
            >
              开始对比
            </button>
          )}
        </div>
      )}

      {/* Timeline content */}
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {loading && <ReportSkeleton />}

        {!loading && filtered.length === 0 && <EmptyState />}

        {!loading &&
          groups.map((group) => (
            <TimelineGroup
              key={group.key}
              group={group}
              defaultExpanded={
                group.key === 'today'
                || group.key === 'yesterday'
                || groups.length === 1
                || group.items.some((item) => item.report_id === selectedReportId)
              }
              selectedReportId={selectedReportId}
              compareIds={compareIds}
              compareMode={compareMode}
              onToggleCompare={handleToggleCompare}
              onViewReport={handleViewReport}
            />
          ))}
      </div>
    </Card>
  );
}

export { ReportSection };
export type { ReportSectionProps };

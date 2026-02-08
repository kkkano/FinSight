import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, Inbox, Library, Search } from 'lucide-react';

import type { ReportIndexItem } from '../../api/client';
import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';
import { Input } from '../ui/Input';

type SortMode = 'date' | 'confidence';

interface ReportSectionProps {
  symbol: string;
  reports: ReportIndexItem[];
  loading: boolean;
}

const MAX_VISIBLE = 8;

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

function ReportSection({ symbol, reports, loading }: ReportSectionProps) {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('date');

  const filtered = useMemo(() => {
    const query = filter.trim().toLowerCase();
    const base = query
      ? reports.filter((item) => {
          const title = (item.title || '').toLowerCase();
          const ticker = (item.ticker || '').toLowerCase();
          const reportId = (item.report_id || '').toLowerCase();
          return (
            title.includes(query) ||
            ticker.includes(query) ||
            reportId.includes(query)
          );
        })
      : reports;

    const sorted = [...base].sort((a, b) => {
      if (sortMode === 'confidence') {
        return (b.confidence_score ?? 0) - (a.confidence_score ?? 0);
      }
      // default: date descending
      const bDate = Date.parse(b.generated_at || b.created_at || '');
      const aDate = Date.parse(a.generated_at || a.created_at || '');
      if (!Number.isNaN(bDate) && !Number.isNaN(aDate)) {
        return bDate - aDate;
      }
      return 0;
    });

    return sorted.slice(0, MAX_VISIBLE);
  }, [reports, filter, sortMode]);

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-3 text-fin-text font-semibold text-sm">
        <Library size={16} className="text-fin-primary" />
        最新收录研报
      </div>

      {/* Filter & Sort Controls */}
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

      {/* Content */}
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {loading ? <ReportSkeleton /> : null}

        {!loading && filtered.length === 0 ? <EmptyState /> : null}

        {!loading &&
          filtered.map((item) => (
            <button
              key={item.report_id}
              type="button"
              onClick={() =>
                navigate(
                  `/chat?report_id=${encodeURIComponent(item.report_id)}`,
                )
              }
              className="w-full text-left p-2 rounded-lg border border-fin-border hover:border-fin-primary/50 hover:bg-fin-bg transition-colors"
            >
              <div className="text-xs text-fin-text font-medium truncate">
                {item.title || item.report_id}
              </div>
              <div className="text-2xs text-fin-muted mt-1 truncate">
                {item.ticker || symbol} &middot;{' '}
                {item.generated_at || 'unknown'}
                {typeof item.confidence_score === 'number'
                  ? ` \u00B7 ${(item.confidence_score * 100).toFixed(0)}%`
                  : ''}
              </div>
              {Array.isArray(item.tags) && item.tags.length > 0 ? (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {item.tags.includes('compare') ? (
                    <Badge variant="info">对比</Badge>
                  ) : null}
                  {item.tags.includes('conflict') ? (
                    <Badge variant="warning">证据冲突</Badge>
                  ) : null}
                  {item.tags.includes('filing') ? (
                    <Badge variant="success">Filing</Badge>
                  ) : null}
                </div>
              ) : null}
            </button>
          ))}
      </div>
    </Card>
  );
}

export { ReportSection };
export type { ReportSectionProps };

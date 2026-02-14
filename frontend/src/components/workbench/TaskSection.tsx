import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, FileSearch, ListTodo, Newspaper, Sparkles } from 'lucide-react';

import type { ReportIndexItem } from '../../api/client';
import type { NewsItem } from '../../types/dashboard';
import { Card } from '../ui/Card';

interface TaskSectionProps {
  symbol: string;
  latestReports: ReportIndexItem[];
  newsItems: NewsItem[];
}

interface TaskItem {
  id: string;
  icon: 'report' | 'news' | 'stale' | 'generate';
  text: string;
  action: () => void;
}

const MAX_TASKS = 5;

const ICON_MAP = {
  report: FileSearch,
  news: Newspaper,
  stale: AlertTriangle,
  generate: Sparkles,
} as const;

function daysBetween(dateStr: string): number {
  const then = Date.parse(dateStr);
  if (Number.isNaN(then)) return 0;
  const now = Date.now();
  return Math.floor((now - then) / (1000 * 60 * 60 * 24));
}

function formatRelativeTime(dateStr: string): string {
  const days = daysBetween(dateStr);
  if (days < 1) return '今天';
  if (days === 1) return '1 天前';
  return `${String(days)} 天前`;
}

function TaskSection({ symbol, latestReports, newsItems }: TaskSectionProps) {
  const navigate = useNavigate();

  const tasks = useMemo(() => {
    const result: TaskItem[] = [];

    // ── 1. 最新研报（最多 2 条，避免挤占其他类别） ──
    const MAX_REPORT_TASKS = 2;
    const recentReports = latestReports.slice(0, MAX_REPORT_TASKS);
    for (const report of recentReports) {
      const ticker = report.ticker || symbol;
      const time = report.generated_at
        ? formatRelativeTime(report.generated_at)
        : 'unknown';
      result.push({
        id: `review-${report.report_id}`,
        icon: 'report',
        text: `查看 ${ticker} 最新研报（生成于 ${time}）`,
        action: () =>
          navigate(
            `/chat?report_id=${encodeURIComponent(report.report_id)}`,
          ),
      });
    }

    // ── 2. 未读快讯 ──
    if (newsItems.length > 0) {
      result.push({
        id: 'unread-news',
        icon: 'news',
        text: `${String(newsItems.length)} 条未读快讯（${symbol}）`,
        action: () =>
          navigate(`/dashboard/${encodeURIComponent(symbol)}`),
      });
    }

    // ── 3. 过期研报提醒（最多 1 条） ──
    const staleReport = latestReports.find((r) => {
      const dateStr = r.generated_at || r.created_at || '';
      return daysBetween(dateStr) >= 3;
    });
    if (staleReport && result.length < MAX_TASKS) {
      const ticker = staleReport.ticker || symbol;
      const days = daysBetween(
        staleReport.generated_at || staleReport.created_at || '',
      );
      result.push({
        id: `stale-${staleReport.report_id}`,
        icon: 'stale',
        text: `${ticker} 研报已 ${String(days)} 天未更新 -- 建议刷新`,
        action: () => {
          navigate('/chat');
        },
      });
    }

    // ── 4. 生成新分析（常驻） ──
    if (result.length < MAX_TASKS) {
      result.push({
        id: 'generate-new',
        icon: 'generate',
        text: `为 ${symbol} 生成新的深度分析`,
        action: () => {
          navigate('/chat');
        },
      });
    }

    return result.slice(0, MAX_TASKS);
  }, [latestReports, newsItems, symbol, navigate]);

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-3 text-fin-text font-semibold text-sm">
        <ListTodo size={16} className="text-fin-primary" />
        今日任务
      </div>
      <div className="space-y-1.5">
        {tasks.length === 0 ? (
          <div className="text-xs text-fin-muted py-2">暂无建议任务</div>
        ) : null}
        {tasks.map((task) => {
          const IconComponent = ICON_MAP[task.icon];
          return (
            <button
              key={task.id}
              type="button"
              onClick={task.action}
              className="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-fin-text-secondary hover:bg-fin-hover hover:text-fin-text transition-colors group"
            >
              <IconComponent
                size={14}
                className="text-fin-muted group-hover:text-fin-primary shrink-0 transition-colors"
              />
              <span className="truncate">{task.text}</span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

export { TaskSection };
export type { TaskSectionProps };

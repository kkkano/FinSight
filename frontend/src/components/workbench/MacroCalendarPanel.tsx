/**
 * MacroCalendarPanel.tsx —— 宏观日历面板（工作台右栏）
 *
 * 展示未来若干天内已确认日期的重要事件（宏观 / 财报 / 分红），
 * 时间线式按日期分组，帮助用户提前感知风险窗口。
 *
 * - 挂载时加载 + 手动刷新
 * - kind badge：macro=紫 / earnings=琥珀 / dividend=绿
 * - 空 / 加载 / 错误态均简洁处理
 * - 样式与工作台其它卡片一致（bg-fin-card rounded-xl border border-fin-border）
 */
import { useCallback, useEffect, useState } from 'react';
import { CalendarClock, RefreshCw } from 'lucide-react';

import { apiClient } from '../../api/client';
import type { MacroCalendarEvent } from '../../types/monitor';
import { KIND_VISUAL, describeDaysUntil, groupByDate } from './macroCalendarHelpers';

interface MacroCalendarPanelProps {
  sessionId: string | null | undefined;
}

/** 未来天数窗口（与契约默认对齐） */
const DAYS_AHEAD = 14;

/**
 * 事件时间线（纯展示组件，便于单测）。
 * 按日期分组渲染；不含加载/错误/空态（由父组件决定何时渲染）。
 */
export function MacroEventTimeline({ events }: { events: MacroCalendarEvent[] }) {
  const grouped = groupByDate(events);
  return (
    <div className="divide-y divide-fin-border/40">
      {grouped.map(([date, dayEvents]) => (
        <div key={date} className="px-4 py-2.5" data-testid={`macro-calendar-date-${date}`}>
          {/* 日期标头 */}
          <div className="flex items-baseline gap-2 mb-1.5">
            <span className="text-2xs font-medium text-fin-text-secondary tabular-nums">{date}</span>
            <span className="text-2xs text-fin-muted">{describeDaysUntil(dayEvents[0].days_until)}</span>
          </div>
          {/* 当天事件 */}
          <div className="space-y-1.5">
            {dayEvents.map((ev, idx) => {
              const visual = KIND_VISUAL[ev.kind];
              return (
                <div
                  key={`${date}-${idx}`}
                  className="flex items-center gap-2 text-xs"
                  data-testid="macro-calendar-event"
                >
                  <span className={`shrink-0 px-1.5 py-0.5 rounded text-2xs ${visual.cls}`}>
                    {visual.label}
                  </span>
                  <span className="flex-1 min-w-0 truncate text-fin-text">{ev.title}</span>
                  {ev.ticker && (
                    <span className="shrink-0 px-1.5 py-0.5 rounded text-2xs bg-fin-border/30 text-fin-muted tabular-nums">
                      {ev.ticker}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function MacroCalendarPanel({ sessionId }: MacroCalendarPanelProps) {
  const [events, setEvents] = useState<MacroCalendarEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) {
      setEvents([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.getMonitorMacroCalendar(sessionId, DAYS_AHEAD);
      setEvents(res.events ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载宏观日历失败');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="bg-fin-card border border-fin-border rounded-xl overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-fin-border">
        <div className="flex items-center gap-2">
          <CalendarClock size={14} className="text-fin-primary" />
          <span className="text-xs font-semibold text-fin-text">宏观日历</span>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          aria-label="刷新宏观日历"
          title="刷新"
          data-testid="macro-calendar-refresh"
          className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-lg bg-fin-primary/10 text-fin-primary hover:bg-fin-primary/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          刷新
        </button>
      </div>

      {error && (
        <div className="px-4 py-2 text-2xs text-fin-danger bg-fin-danger/10 border-b border-fin-border">
          {error}
        </div>
      )}

      {/* 内容区 */}
      {loading && events.length === 0 ? (
        <div className="py-6 text-center text-xs text-fin-muted">正在加载宏观日历...</div>
      ) : events.length === 0 ? (
        <div className="py-6 text-center text-xs text-fin-muted px-4">
          未来 {DAYS_AHEAD} 天暂无已确认日期的重要事件
        </div>
      ) : (
        <MacroEventTimeline events={events} />
      )}
    </div>
  );
}

export default MacroCalendarPanel;

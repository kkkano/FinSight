/**
 * macroCalendarHelpers.ts —— 宏观日历面板的纯函数工具
 *
 * 从 MacroCalendarPanel.tsx 抽出，满足 react-refresh/only-export-components
 * （组件文件只导出组件，纯函数单独成文件，便于单测）。
 */
import type { MacroCalendarEvent, MacroEventKind } from '../../types/monitor';

/** kind badge 文案 + 配色（紫/琥珀/绿用 Tailwind 原生色，避免 fin-* alpha 陷阱） */
export const KIND_VISUAL: Record<MacroEventKind, { label: string; cls: string }> = {
  macro: { label: '宏观', cls: 'bg-purple-500/15 text-purple-300' },
  earnings: { label: '财报', cls: 'bg-amber-500/15 text-amber-300' },
  dividend: { label: '分红', cls: 'bg-green-500/15 text-green-300' },
};

/** 把 days_until 渲染成「今天 / 明天 / N 天后」 */
export function describeDaysUntil(days: number): string {
  if (days <= 0) return '今天';
  if (days === 1) return '明天';
  return `${days} 天后`;
}

/** 按日期分组（保持后端返回的顺序，假定已按日期升序） */
export function groupByDate(
  events: MacroCalendarEvent[],
): Array<[string, MacroCalendarEvent[]]> {
  const map = new Map<string, MacroCalendarEvent[]>();
  for (const ev of events) {
    const list = map.get(ev.date);
    if (list) {
      list.push(ev);
    } else {
      map.set(ev.date, [ev]);
    }
  }
  return Array.from(map.entries());
}

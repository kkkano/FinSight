import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import {
  MacroCalendarPanel,
  MacroEventTimeline,
  describeDaysUntil,
  groupByDate,
} from './MacroCalendarPanel';
import type { MacroCalendarEvent } from '../../types/monitor';

// 静态渲染不触发 useEffect / 真实请求，但 mock 掉以隔离副作用
vi.mock('../../api/client', () => ({
  apiClient: {
    getMonitorMacroCalendar: vi.fn(),
  },
}));

const renderText = (node: React.ReactElement) =>
  renderToStaticMarkup(node).replace(/\s+/g, ' ');

function makeEvents(): MacroCalendarEvent[] {
  return [
    { date: '2026-06-15', title: 'FOMC 利率决议', days_until: 12, kind: 'macro', ticker: null, source: 'fed' },
    { date: '2026-06-18', title: 'AAPL 财报发布', days_until: 15, kind: 'earnings', ticker: 'AAPL', source: 'edgar' },
    { date: '2026-06-18', title: 'MSFT 除息日', days_until: 15, kind: 'dividend', ticker: 'MSFT', source: 'edgar' },
  ];
}

describe('describeDaysUntil', () => {
  it('today / tomorrow / N days', () => {
    expect(describeDaysUntil(0)).toBe('今天');
    expect(describeDaysUntil(1)).toBe('明天');
    expect(describeDaysUntil(12)).toBe('12 天后');
  });
});

describe('groupByDate', () => {
  it('同一天的事件合并到一组', () => {
    const grouped = groupByDate(makeEvents());
    expect(grouped).toHaveLength(2); // 06-15 一组、06-18 一组
    const [, june18] = grouped;
    expect(june18[0]).toBe('2026-06-18');
    expect(june18[1]).toHaveLength(2);
  });
});

describe('MacroEventTimeline', () => {
  it('渲染事件标题、kind badge、天数与 ticker', () => {
    const text = renderText(<MacroEventTimeline events={makeEvents()} />);
    // 标题
    expect(text).toContain('FOMC 利率决议');
    expect(text).toContain('AAPL 财报发布');
    expect(text).toContain('MSFT 除息日');
    // kind badge
    expect(text).toContain('宏观');
    expect(text).toContain('财报');
    expect(text).toContain('分红');
    // 天数（分组标头取首条）
    expect(text).toContain('12 天后');
    // ticker
    expect(text).toContain('AAPL');
    expect(text).toContain('MSFT');
    // 日期分组
    expect(text).toContain('2026-06-15');
    expect(text).toContain('2026-06-18');
  });
});

describe('MacroCalendarPanel', () => {
  it('挂载时（无 sessionId / effect 未执行）展示空状态文案', () => {
    const text = renderText(<MacroCalendarPanel sessionId={null} />);
    expect(text).toContain('未来 14 天暂无已确认日期的重要事件');
    // 头部标题与刷新按钮
    expect(text).toContain('宏观日历');
    expect(text).toContain('macro-calendar-refresh');
  });
});

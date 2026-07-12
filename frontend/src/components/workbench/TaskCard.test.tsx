import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import type { DailyTask } from '../../api/client';
import { TaskCard } from './TaskCard';

const executableTask: DailyTask = {
  id: 'task-aapl',
  title: 'AAPL 价格异动分析',
  category: 'anomaly',
  priority: 1,
  action_url: '/chat?query=AAPL',
  icon: 'alert-triangle',
  reason: 'AAPL 日跌幅 -4.2%，建议分析原因',
  execution_params: { query: '分析 AAPL 价格异动原因', tickers: ['AAPL'] },
};

describe('TaskCard', () => {
  it('明确展示任务原因与执行入口', () => {
    const html = renderToStaticMarkup(
      <TaskCard
        task={executableTask}
        run={undefined}
        onClick={vi.fn()}
        onResume={vi.fn()}
        onCancelInterrupt={vi.fn()}
      />,
    );

    expect(html).toContain('AAPL 价格异动分析');
    expect(html).toContain('AAPL 日跌幅 -4.2%');
    expect(html).toContain('去执行 →');
  });
});

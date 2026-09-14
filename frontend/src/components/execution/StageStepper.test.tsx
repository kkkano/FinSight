import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { StageStepper } from './StageStepper';

describe('StageStepper', () => {
  it('renders done, active, pending and error states with elapsed time and action', () => {
    const html = renderToStaticMarkup(
      <StageStepper
        stages={[
          { key: 'understand', label: '理解', status: 'done' },
          { key: 'plan', label: '计划', status: 'active' },
          { key: 'execute', label: '执行', status: 'pending', detail: '2/5' },
          { key: 'synthesize', label: '综合', status: 'error' },
        ]}
        elapsedMs={84_000}
        currentAction="基本面分析师 · 检索 8 季度财报"
      />,
    );

    expect(html).toContain('理解：已完成');
    expect(html).toContain('计划：进行中');
    expect(html).toContain('执行：等待中');
    expect(html).toContain('综合：失败');
    expect(html).toContain('animate-pulse');
    expect(html).not.toContain('animate-ping');
    expect(html).toContain('执行(2/5)');
    expect(html).toContain('1m24s');
    expect(html).toContain('基本面分析师 · 检索 8 季度财报');
    expect(html).toMatchSnapshot();
  });
});

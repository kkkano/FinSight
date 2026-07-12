import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { AgentControlPanel } from './AgentControlPanel';

describe('AgentControlPanel', () => {
  it('explains that preferences control the default report agents', () => {
    const markup = renderToStaticMarkup(<AgentControlPanel />);

    expect(markup).toContain('控制报告默认参与的智能体及研究深度');
    expect(markup.match(/data-testid="agent-depth-[^"]+-standard"/g)).toHaveLength(7);
    expect(markup).toContain('data-testid="agent-reflection-rounds"');
  });
});

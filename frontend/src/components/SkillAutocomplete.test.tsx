import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { SkillAutocomplete } from './SkillAutocomplete';

describe('SkillAutocomplete', () => {
  it('shows the real available skill count in the slash-command hint', () => {
    const markup = renderToStaticMarkup(
      <SkillAutocomplete
        skills={[{
          name: 'valuation-sanity-check',
          description: 'Check valuation against growth and risk.',
          risk_level: 'medium',
          required_facets: {},
          preferred_tools: ['get_stock_price'],
          preferred_agents: ['fundamental_agent'],
          optional_python_operations: [],
          budget: {},
          insert_text: '/skill valuation-sanity-check ',
        }]}
        totalCount={7}
        selectedIndex={0}
        onSelect={() => undefined}
        onOpenLibrary={() => undefined}
      />,
    );

    expect(markup).toContain('7 个可用技能 · 输入名称筛选');
  });
});

import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { HistoryPage } from './HistoryPage';

describe('History 页面', () => {
  it('首屏明确区分 Predictions 与 Reports', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/history']}>
        <HistoryPage />
      </MemoryRouter>,
    );

    expect(html).toContain('Prediction、Outcome 与研究报告的持久化记录');
    expect(html).toContain('Predictions');
    expect(html).toContain('Reports');
    expect(html).toContain('统计窗口：最近 90 天');
  });
});

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { Message } from '../types';
import { RightPanel } from './RightPanel';

const state = vi.hoisted(() => ({ messages: [] as Message[], sessionId: 'source-title-test' }));
vi.mock('../store/useStore', () => ({ useStore: (selector: (value: typeof state) => unknown) => selector(state) }));
vi.mock('./right-panel/RightPanelMarket', () => ({ RightPanelMarket: () => null }));

describe('right panel source titles', () => {
  it('maps actual ledger fallback identifiers while retaining original article titles', () => {
    state.messages = [{ id: 'a1', role: 'assistant', runId: 'run1', content: '已核查行情。', timestamp: 1,
      evidence_pool: [{ source_id: 'S1', title: 'twelve_data' }, { source_id: 'S2', title: 'get_stock_historical_data' },
        { source_id: 'S3', title: 'market_chart' }, { source_id: 'S4', title: 'AAPL_2026_Q4：公司业绩公告' }] }];
    const visible = renderToStaticMarkup(<RightPanel symbol="AAPL" onCollapse={() => undefined} />).replace(/<[^>]+>/g, '');
    expect(visible).toContain('Twelve Data');
    expect(visible).toContain('历史行情数据');
    expect(visible).toContain('行情图表数据');
    expect(visible).toContain('AAPL_2026_Q4：公司业绩公告');
    expect(visible).not.toMatch(/twelve_data|market_chart|get_stock/);
  });
});

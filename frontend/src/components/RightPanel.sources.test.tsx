import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { Message } from '../types';
import { RightPanel } from "./RightPanel";
import { observedMessageTickers } from "./RightPanel.utils";

const state = vi.hoisted(() => ({ messages: [] as Message[], sessionId: 'source-title-test' }));
vi.mock('../store/useStore', () => ({ useStore: (selector: (value: typeof state) => unknown) => selector(state) }));
vi.mock('./right-panel/RightPanelMarket', () => ({ RightPanelMarket: () => null }));

describe('right panel source titles', () => {
  it('takes the ticker from structured tool parameters and ignores user wording', () => {
    const message: Message = { id: 'scope', role: 'assistant', content: '旧的 AAPL 描述', timestamp: 1,
      requestSnapshot: { query: '提到 TSLA 的原话' } as Message['requestSnapshot'], thinking: [
        { stage: 'tool_start', timestamp: '2026-11-11T00:00:00Z', result: { inputs: { ticker: 'NVDA' } } },
        { stage: 'tool_end', timestamp: '2026-11-11T00:00:01Z', result: { payload: { inputs: { ticker: 'NVDA' } } } },
      ] };
    expect(observedMessageTickers(message)).toEqual(['NVDA']);
  });
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

  it('retains clickable sources for research without a stock symbol', () => {
    state.messages = [{ id: 'macro', role: 'assistant', runId: 'macro-run', content: '已核查宏观数据。', timestamp: 1,
      evidence_pool: [{ source_id: 'Sabc', title: '美国利率数据', source: 'fred' }] }];
    const html = renderToStaticMarkup(<RightPanel onCollapse={() => undefined} />);
    expect(html).toContain('参考来源');
    expect(html).toContain('data-source-id="Sabc"');
    expect(html).toContain('aria-label="查看来源 1 详情"');
    expect(html).not.toContain('聊到股票时');
  });
});

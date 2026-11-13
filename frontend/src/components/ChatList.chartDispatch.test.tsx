import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from './ui/Toast';
import type { Message } from '../types';
import { ChatList } from './ChatList';
import { useStore } from '../store/useStore';
import { InlineChart } from './InlineChart';
import { getRenderableMessageContent, parseSmartChartBlocks, resolveRealPriceChartRequest } from './SmartChart';

vi.mock('../store/useStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../store/useStore')>();
  return { ...actual, useStore: Object.assign((selector?: (state: ReturnType<typeof actual.useStore.getState>) => unknown) =>
    selector ? selector(actual.useStore.getState()) : actual.useStore.getState(), actual.useStore) };
});
vi.mock('../hooks/useChatStream', () => ({ useChatStream: () => ({ retry: vi.fn() }) }));
vi.mock('./charts/EChart', () => ({ default: () => <div data-testid="artifact-chart-canvas" /> }));
vi.mock('./InlineChart', () => ({ InlineChart: vi.fn(({ ticker, chartType }: { ticker: string; chartType: string }) =>
  <div data-testid="legacy-inline-chart">{ticker} · {chartType}</div>) }));
vi.mock('./SmartChart', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./SmartChart')>();
  return { ...actual, parseSmartChartBlocks: vi.fn(actual.parseSmartChartBlocks),
    getRenderableMessageContent: vi.fn(actual.getRenderableMessageContent), resolveRealPriceChartRequest: vi.fn(actual.resolveRealPriceChartRequest) };
});

const content = 'AAPL 资料见 [S1]。\n\n[CHART:NVDA:line:close:1y]\n\n<chart type="candlestick" symbol="AAPL" title="价格">{"labels":["D1"],"values":[999999]}</chart>';
const message: Message = { id: 'answer', role: 'assistant', content, timestamp: 2, runId: 'ui-protocol-run',
  evidence_pool: [{source_id:'S1',title:'界面来源',url:'https://example.test/source'}] };
const artifact = { id: 'artifact', kind: 'artifact' as const, revision: 0,
  artifact: { artifact_id: 'ui-artifact', kind: 'chart' as const, title: '协议夹具图表', source_refs: ['S1'],
    spec: { chart_type: 'line', x: 'date', series: [{ field: 'close', name: '收盘价', unit: 'USD' }] },
    data: { rows: [{date:'2026-11-01',close:10},{date:'2026-11-02',close:11}] } } };

function renderMessage(value: Message) {
  useStore.setState({ messages: [{id:'question',role:'user',content:'界面合同问题',timestamp:1}, value] });
  return renderToStaticMarkup(<MemoryRouter><ToastProvider><ChatList /></ToastProvider></MemoryRouter>);
}

function expectNoLegacyChart() {
  expect(parseSmartChartBlocks).not.toHaveBeenCalled();
  expect(getRenderableMessageContent).not.toHaveBeenCalled();
  expect(resolveRealPriceChartRequest).not.toHaveBeenCalled();
  expect(InlineChart).not.toHaveBeenCalled();
}

describe('message chart delivery boundary', () => {
  beforeEach(() => vi.clearAllMocks());
  it('renders only the returned artifact for a research message and preserves numbered citations and ticker links', () => {
    const markup = renderMessage({...message,blocks:[{id:'body',kind:'text',content,revision:0},artifact]});
    expect(markup).toContain('协议夹具图表');
    expect(markup.match(/<figure/g)).toHaveLength(1);
    expect(markup).toContain('aria-label="查看引用 1"');
    expect(markup).toContain('/dashboard/AAPL');
    expectNoLegacyChart();
  });
  it('treats an explicitly empty blocks array as a research message and does not upgrade body markers into charts', () => {
    const markup = renderMessage({...message,blocks:[]});
    expect(markup).not.toContain('legacy-inline-chart');
    expect(markup).toContain('aria-label="查看引用 1"');
    expectNoLegacyChart();
  });
  it('binds a numeric citation to its provided source ID even when it is not the list position', () => {
    const markup=renderMessage({...message,content:'引用[3]；未知[1]',blocks:[],
      evidence_pool:[{source_id:'3',title:'整数来源',url:'https://example.test/3'}]});
    expect(markup).toContain('href="#research-source-3"');
    expect(markup).toContain('未知[1]');
    expectNoLegacyChart();
  });
  it('keeps the pure body fallback when text is separate from the artifact blocks', () => {
    const markup = renderMessage({...message,blocks:[artifact]});
    expect(markup).toContain('协议夹具图表');
    expect(markup).toContain('AAPL');
    expectNoLegacyChart();
  });
  it('retains the real-market chart compatibility path for historical messages without blocks', () => {
    const markup = renderMessage(message);
    expect(parseSmartChartBlocks).toHaveBeenCalledWith(content);
    expect(resolveRealPriceChartRequest).toHaveBeenCalled();
    expect(InlineChart).toHaveBeenCalled();
    expect(markup).toContain('legacy-inline-chart');
    expect(markup).toContain('AAPL · candlestick');
    expect(markup).not.toContain('[CHART:');
    expect(markup).not.toContain('999999');
    expect(markup).toContain('aria-label="查看引用 1"');
  });
});

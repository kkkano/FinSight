import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  ConceptTable,
  FundFlowTable,
  LhbTable,
  LimitBoardTable,
} from './CNMarketPanel';

/** 把 JSX 渲染为静态 HTML 字符串 */
const render = (node: React.ReactElement) => renderToStaticMarkup(node);

/** 统计字符串里某子串出现的次数 */
const countOf = (haystack: string, needle: string) =>
  haystack.split(needle).length - 1;

// ── Mock 行数据 ───────────────────────────────────────────────

const fundFlowRows = [
  { symbol: '600519', name: '贵州茅台', change_percent: 2.35, main_net_inflow: 1.23e8 },
  { symbol: '000858', name: '五粮液', change_percent: -1.12, main_net_inflow: -4.5e7 },
];

const limitBoardRows = [
  { symbol: '300750', name: '宁德时代', change_percent: 10.0, turnover_rate: '8.5', volume_ratio: '3.2' },
];

const lhbRows = [
  { symbol: '002594', name: '比亚迪', change_percent: 5.6, net_buy: 8.8e7, reason: '日涨幅偏离值达7%的证券' },
];

const conceptRows = [
  { concept_code: 'BK0900', concept_name: '人工智能', change_percent: 3.14, main_net_inflow: 2.2e8, up_count: 42, down_count: 8 },
];

// ── whitespace-nowrap 横向滚动适配断言 ──────────────────────────

describe('CNMarketPanel tables — 移动端横向滚动适配', () => {
  it('FundFlowTable: 每个表头/单元格都带 whitespace-nowrap', () => {
    const html = render(<FundFlowTable rows={fundFlowRows} />);
    // 4 个 th + 每行 4 个 td * 2 行 = 4 + 8 = 12 处 whitespace-nowrap
    expect(countOf(html, 'whitespace-nowrap')).toBe(12);
  });

  it('LimitBoardTable: 每个表头/单元格都带 whitespace-nowrap', () => {
    const html = render(<LimitBoardTable rows={limitBoardRows} />);
    // 5 个 th + 每行 5 个 td * 1 行 = 5 + 5 = 10
    expect(countOf(html, 'whitespace-nowrap')).toBe(10);
  });

  it('LhbTable: 每个表头/单元格都带 whitespace-nowrap', () => {
    const html = render(<LhbTable rows={lhbRows} />);
    // 5 个 th + 每行 5 个 td * 1 行 = 5 + 5 = 10
    expect(countOf(html, 'whitespace-nowrap')).toBe(10);
  });

  it('ConceptTable: 每个表头/单元格都带 whitespace-nowrap', () => {
    const html = render(<ConceptTable rows={conceptRows} />);
    // 4 个 th + 每行 4 个 td * 1 行 = 4 + 4 = 8
    expect(countOf(html, 'whitespace-nowrap')).toBe(8);
  });

  it('FundFlowTable: 名称列同时保留 truncate 与 whitespace-nowrap（两者不冲突）', () => {
    const html = render(<FundFlowTable rows={fundFlowRows} />);
    // 名称单元格应同时含 truncate 和 whitespace-nowrap
    const cellMatch = html.match(/class="[^"]*truncate[^"]*"/);
    expect(cellMatch?.[0] ?? '').toContain('whitespace-nowrap');
    // 仍保留宽度约束 max-w
    expect(html).toContain('max-w-[80px]');
  });
});

// ── 数据正常渲染断言 ───────────────────────────────────────────

describe('CNMarketPanel tables — 数据渲染', () => {
  it('FundFlowTable: mock 行数据出现在输出中', () => {
    const html = render(<FundFlowTable rows={fundFlowRows} />);
    expect(html).toContain('600519');
    expect(html).toContain('贵州茅台');
    expect(html).toContain('+2.35%');
    expect(html).toContain('1.23亿'); // fmtFlow 大额单位
  });

  it('LimitBoardTable: mock 行数据出现在输出中', () => {
    const html = render(<LimitBoardTable rows={limitBoardRows} />);
    expect(html).toContain('300750');
    expect(html).toContain('宁德时代');
    expect(html).toContain('+10.00%');
    expect(html).toContain('8.5'); // 换手率
  });

  it('LhbTable: mock 行数据出现在输出中', () => {
    const html = render(<LhbTable rows={lhbRows} />);
    expect(html).toContain('002594');
    expect(html).toContain('比亚迪');
    expect(html).toContain('日涨幅偏离值达7%的证券'); // 上榜原因
  });

  it('ConceptTable: mock 行数据出现在输出中', () => {
    const html = render(<ConceptTable rows={conceptRows} />);
    expect(html).toContain('人工智能');
    expect(html).toContain('+3.14%');
    expect(html).toContain('42'); // up_count
    expect(html).toContain('8'); // down_count
  });

  it('空数据时表头仍渲染、无数据行', () => {
    const html = render(<FundFlowTable rows={[]} />);
    expect(html).toContain('代码');
    expect(html).toContain('主力净流入');
    expect(html).not.toContain('<tr class="hover');
  });
});

import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PredictionHistoryItem, PredictionStatsResponse } from '../api/domains/predictions';
import { HistoryPage } from './HistoryPage';
import { formatPercentagePoints, formatRatioPercent } from './historyFormatting';

const history = vi.hoisted(() => ({
  items: [] as PredictionHistoryItem[],
  stats: null as PredictionStatsResponse['stats'] | null,
  loading: false,
}));

vi.mock('../hooks/usePredictionHistory', () => ({
  usePredictionHistory: () => ({ ...history, failure: null, refresh: vi.fn() }),
  usePredictionRun: () => ({ llm_provider: 'StepFun', llm_model: 'step-5-preview' }),
}));

function renderHistory() {
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={['/history']}>
      <HistoryPage />
    </MemoryRouter>,
  );
}

describe('History 页面', () => {
  beforeEach(() => {
    history.items = [];
    history.stats = null;
    history.loading = false;
  });

  it('首屏使用清楚的中文视图名称', () => {
    const html = renderHistory();

    expect(html).toContain('历史记录');
    expect(html).toContain('AI 判断');
    expect(html).toContain('研究报告');
    expect(html).toContain('最近 90 天');
    expect(html).toContain('暂无 AI 判断记录');
    expect(html).not.toContain('0.0%');
  });

  it('详情按百分点展示行情变动与情景概率，命中率按比例展示', () => {
    history.items = [{
      prediction: {
        prediction_id: 'prediction-aapl',
        run_id: 'run-aapl',
        symbol: 'AAPL',
        agent: 'technical',
        direction: 'long',
        confidence: 60,
        thesis: '趋势仍然偏多，关注前高附近的量价表现。',
        anchor: { timeframe: '1d', time: '2026-10-01', price: 200 },
        scenarios: [{ name: '低概率回撤', probability: 0.5, invalidation: '跌破支撑。' }],
        status: 'open',
        prompt_version: 'v1',
        source_type: 'ai',
        created_at: '2026-10-01T08:00:00Z',
        updated_at: '2026-10-01T08:00:00Z',
      },
      outcome: {
        prediction_id: 'prediction-aapl',
        status: 'open',
        pct_since_anchor: -2.001,
        algorithm_version: 'outcome-v1',
      },
    }];
    history.stats = {
      days: 90,
      symbol: null,
      predictions: 10,
      resolved: 8,
      hits: 6,
      misses: 2,
      invalidated: 0,
      hit_rate: 0.75,
      by_source: {},
      by_direction: {},
    };

    const html = renderHistory();

    expect(html).toContain('-2.0%');
    expect(html).not.toContain('-200.1%');
    expect(html).toContain('情景概率 0.5%');
    expect(html).toContain('75.0%');
    expect(html).toContain('判断结果');
    expect(html).toContain('StepFun / step-5-preview');
    expect(html).toContain('aria-pressed="true"');
  });
});

describe('历史百分比单位', () => {
  it.each([
    [-2.001, '-2.0%'],
    [-0.5, '-0.5%'],
    [0, '0.0%'],
    [0.5, '0.5%'],
    [1, '1.0%'],
    [100, '100.0%'],
  ])('百分点 %s 保持其单位', (value, expected) => {
    expect(formatPercentagePoints(value)).toBe(expected);
  });

  it.each([
    [0, '0.0%'],
    [0.005, '0.5%'],
    [0.5, '50.0%'],
    [1, '100.0%'],
  ])('比例 %s 转换为百分比', (value, expected) => {
    expect(formatRatioPercent(value)).toBe(expected);
  });

  it.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY])('缺失或无效值 %s 显示占位符', (value) => {
    expect(formatPercentagePoints(value)).toBe('--');
    expect(formatRatioPercent(value)).toBe('--');
  });
});

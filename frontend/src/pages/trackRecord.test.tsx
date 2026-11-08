import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { TrackRecordContent } from './TrackRecordPage';
import { BenchmarkRecordDetail } from '../components/track-record/BenchmarkTrackRecord';
import { formatDelta, formatEtTime, formatHitRate, formatRatio, predictionLabel, sortRecentRecords, statusLabel } from './trackRecord';
import { makeEmptyTrackRecordFixture, makePendingTrackRecordFixture, makeTrackRecordFixture } from './trackRecord.fixtures';

describe('prediction track record presentation', () => {
  it('keeps a settlement calendar date on the same day', () => {
    expect(formatEtTime('2026-09-25')).toBe('2026/09/25');
  });

  it('keeps internal task names out of visible record text and follows metadata thresholds', () => {
    const data = makeTrackRecordFixture();
    data.metadata = { ...data.metadata, horizon_sessions: 7, drawdown_threshold: 0.08, min_sample_size: 100 };
    const text = renderToStaticMarkup(<TrackRecordContent data={data} />).replace(/<[^>]*>/g, ' ');
    expect(text).not.toMatch(/\b(?:TP|FP|FN|TN|P0|P5|Risk|Technical|US20)\b/i);
    expect(text).toContain('7 个交易日');
    expect(text).toContain('8.0%');
    expect(text).toContain('100 条已对账');
  });

  it('formats API ratios as percentages and differences as percentage points', () => {
    expect(formatRatio(0.03)).toBe('3.0%');
    expect(formatRatio(0.005)).toBe('0.5%');
    expect(formatDelta(-0.5, 4)).toBe('-50.0 个百分点');
    expect(formatDelta(0.25, 4)).toBe('+25.0 个百分点');
  });

  it('never substitutes zero or perfect accuracy for an empty denominator', () => {
    expect(formatHitRate(0, 0)).toBe('等待首批对账');
    expect(formatHitRate(1, 0)).toBe('等待首批对账');
    expect(formatDelta(0, 0)).toBe('等待首批对账');
    expect(formatHitRate(null, 3)).toBe('暂无');
    expect(formatHitRate(0, 3)).toBe('0.0%');
  });

  it.each([makeEmptyTrackRecordFixture, makePendingTrackRecordFixture])('renders truthful empty or pending states', (makeFixture) => {
    const markup = renderToStaticMarkup(<TrackRecordContent data={makeFixture()} />);
    expect(markup).toContain('等待首批对账');
    expect(markup).not.toContain('AI 命中率');
    expect(markup).not.toContain('100.0%');
    expect(markup).not.toContain('0.0%');
  });

  it('shows losing model groups, unknown identities, both baselines and risk confusion counts', () => {
    const data = makeTrackRecordFixture();
    const markup = renderToStaticMarkup(<TrackRecordContent data={data} />);
    expect(markup).toContain('低 50.0 个百分点');
    expect(markup).toContain('每次都猜涨');
    expect(markup).toContain('direction-unconfirmed-models');
    expect(markup).toContain('模型未确认的记录，单独统计');
    expect(markup).toContain('预警了，真跌了');
    expect(markup).toContain('预警了，没跌（虚惊一场）');
    expect(markup).toContain('没预警，也没跌');
    expect(markup).toContain('没预警，真跌了（漏报）');
    expect(markup).toContain('记录太少');
    expect(markup).toContain('窗口可能重叠');
    expect(markup.match(/data-testid="prediction-record-row"/g)).toHaveLength(40);
  });

  it('keeps failed opportunities alongside settled records and treats negative risk predictions as valid', () => {
    const records = makeTrackRecordFixture().records;
    const sorted = sortRecentRecords(records);
    expect(sorted).toHaveLength(records.length);
    expect(sorted.filter((record) => record.status === 'failed')).toHaveLength(2);
    expect(sorted.filter((record) => record.status === 'settled')).toHaveLength(10);
    expect(predictionLabel(records[3])).toBe('未发出大跌预警');
    expect(predictionLabel(records[37])).toBe('尚无判断');
    expect(statusLabel('queued')).toBe('待采集');
    expect(statusLabel('running')).toBe('采集中');
    expect(statusLabel('interrupted')).toBe('已中断');
  });

  it('only renders declared public fields instead of dumping private payload metadata', () => {
    const data = makeTrackRecordFixture();
    const unsafe = { ...data, endpoint_url: 'https://private.example', session_id: 'private-session', raw_reasoning: 'private-think' };
    Object.assign(unsafe.records[0], { endpoint_url: 'https://private.example', raw_reasoning: 'private-think' });
    const markup = renderToStaticMarkup(<TrackRecordContent data={unsafe} />);
    expect(markup).not.toContain('private.example');
    expect(markup).not.toContain('private-session');
    expect(markup).not.toContain('private-think');
  });

  it('uses the declared prediction table and keeps technical rules collapsed', () => {
    const markup = renderToStaticMarkup(<TrackRecordContent data={makeTrackRecordFixture()} />);
    expect(markup).toContain('<table');
    expect(markup).not.toContain('min-w-[1060px]');
    expect(markup).toContain('规则是怎么定的');
    expect(markup).not.toMatch(/<details[^>]*open/);
  });

  it('shows original prediction, actual prices and source in a record detail without private payloads', () => {
    const data = makeTrackRecordFixture();
    const markup = renderToStaticMarkup(<BenchmarkRecordDetail record={data.records[0]} source={data.metadata.source} />);
    expect(markup).toContain('当时的判断');
    expect(markup).toContain('实际对账行情');
    expect(markup).toContain('100.00');
    expect(markup).toContain('103.00');
    expect(markup).toContain('fixture-model-a');
    expect(markup).toContain('yahoo/yfinance-0.2.66');
  });

  it('keeps pending record outcomes unknown and preserves failed opportunities', () => {
    const data = makeTrackRecordFixture();
    const pending = renderToStaticMarkup(<BenchmarkRecordDetail record={data.records[10]} source={data.metadata.source} />);
    expect(pending).toContain('对账');
    expect(pending).not.toContain('100.0%');
    expect(pending).not.toContain('0.0%');
    const failed = renderToStaticMarkup(<BenchmarkRecordDetail record={data.records[36]} source={data.metadata.source} />);
    expect(failed).not.toContain('fixture_timeout');
    expect(failed).toContain('未取得可评分结果');
  });
});

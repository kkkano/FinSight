import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { TrackRecordContent } from './TrackRecordPage';
import { BenchmarkRecordDetail } from '../components/track-record/BenchmarkTrackRecord';
import { formatDelta, formatHitRate, formatRatio, predictionLabel, sortRecentRecords, statusLabel } from './trackRecord';
import { makeEmptyTrackRecordFixture, makePendingTrackRecordFixture, makeTrackRecordFixture } from './trackRecord.fixtures';

describe('prediction track record presentation', () => {
  it('formats API ratios as percentages and differences as percentage points', () => {
    expect(formatRatio(0.03)).toBe('3.0%');
    expect(formatRatio(0.005)).toBe('0.5%');
    expect(formatDelta(-0.5, 4)).toBe('-50.0 个百分点');
    expect(formatDelta(0.25, 4)).toBe('+25.0 个百分点');
  });

  it('never substitutes zero or perfect accuracy for an empty denominator', () => {
    expect(formatHitRate(0, 0)).toBe('等待首批结算');
    expect(formatHitRate(1, 0)).toBe('等待首批结算');
    expect(formatDelta(0, 0)).toBe('等待首批结算');
    expect(formatHitRate(null, 3)).toBe('待核验');
    expect(formatHitRate(0, 3)).toBe('0.0%');
  });

  it.each([makeEmptyTrackRecordFixture, makePendingTrackRecordFixture])('renders truthful empty or pending states', (makeFixture) => {
    const markup = renderToStaticMarkup(<TrackRecordContent data={makeFixture()} />);
    expect(markup).toContain('等待首批结算');
    expect(markup).not.toContain('AI 命中率');
    expect(markup).not.toContain('100.0%');
    expect(markup).not.toContain('0.0%');
  });

  it('shows losing model groups, unknown identities, both baselines and risk confusion counts', () => {
    const data = makeTrackRecordFixture();
    const markup = renderToStaticMarkup(<TrackRecordContent data={data} />);
    expect(markup).toContain('-50.0 个百分点');
    expect(markup).toContain('-20.0 个百分点');
    expect(markup).toContain('永远看多');
    expect(markup).toContain('始终不发生');
    expect(markup).toContain('direction-unconfirmed-models');
    expect(markup).toContain('模型身份未确认 · 单独统计');
    expect(markup).toContain('TP · 正确预警');
    expect(markup).toContain('FP · 误报');
    expect(markup).toContain('TN · 正确排除');
    expect(markup).toContain('FN · 漏报');
    expect(markup).toContain('20.0%');
    expect(markup).toContain('样本不足');
    expect(markup).toContain('窗口存在重叠');
    expect(markup.match(/data-testid="prediction-record-row"/g)).toHaveLength(40);
  });

  it('keeps failed opportunities alongside settled records and treats negative risk predictions as valid', () => {
    const records = makeTrackRecordFixture().records;
    const sorted = sortRecentRecords(records);
    expect(sorted).toHaveLength(records.length);
    expect(sorted.filter((record) => record.status === 'failed')).toHaveLength(2);
    expect(sorted.filter((record) => record.status === 'settled')).toHaveLength(10);
    expect(predictionLabel(records[3])).toBe('不发生回撤事件');
    expect(predictionLabel(records[37])).toBe('尚无判断');
    expect(statusLabel('queued')).toBe('待采集');
    expect(statusLabel('running')).toBe('采集中');
    expect(statusLabel('interrupted')).toBe('中断待恢复');
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

  it('uses vertical record rows instead of a wide table inside the workspace', () => {
    const markup = renderToStaticMarkup(<TrackRecordContent data={makeTrackRecordFixture()} />);
    expect(markup).not.toContain('<table');
    expect(markup).not.toContain('min-w-[1060px]');
    expect(markup).toContain('明细筛选与翻页不改变统计');
  });

  it('shows original prediction, actual prices and source in a record detail without private payloads', () => {
    const data = makeTrackRecordFixture();
    const markup = renderToStaticMarkup(<BenchmarkRecordDetail record={data.records[0]} source={data.metadata.source} />);
    expect(markup).toContain('预先判断');
    expect(markup).toContain('实际结果');
    expect(markup).toContain('100.00');
    expect(markup).toContain('103.00');
    expect(markup).toContain('fixture-model-a');
    expect(markup).toContain('yahoo/yfinance-0.2.66');
  });

  it('keeps pending record outcomes unknown and preserves failed opportunities', () => {
    const data = makeTrackRecordFixture();
    const pending = renderToStaticMarkup(<BenchmarkRecordDetail record={data.records[10]} source={data.metadata.source} />);
    expect(pending).toContain('不计为命中或未命中');
    expect(pending).not.toContain('100.0%');
    expect(pending).not.toContain('0.0%');
    const failed = renderToStaticMarkup(<BenchmarkRecordDetail record={data.records[36]} source={data.metadata.source} />);
    expect(failed).toContain('fixture_timeout');
    expect(failed).toContain('未形成可评分结果');
  });
});

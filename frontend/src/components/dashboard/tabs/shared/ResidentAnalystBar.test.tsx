import { readFileSync } from 'node:fs';

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { useStore } from '../../../../store/useStore';
import { ResidentAnalystBar } from './ResidentAnalystBar';
import {
  openResidentAnalystChat,
  selectResidentAnalyst,
  type ResidentAnalystProfile,
} from './residentAnalyst';

const profile: ResidentAnalystProfile = {
  name: 'technical_agent', display_name: '技术面分析师', short_zh: '技术面', glyph: 'T',
  color_token: 't-predict', mandate: 'RSI、MACD、均线、形态与交易信号研判',
  scorer_key: 'technical', dashboard_tabs: ['technical', 'overview'],
  track_record: { hit_rate: 0.7, sample_state: 'sufficient' },
};

describe('ResidentAnalystBar', () => {
  it('渲染同源 profile、战绩与两个操作入口', () => {
    const html = renderToStaticMarkup(
      <ResidentAnalystBar tab="technical" profile={profile} onDeepDive={() => {}} onAsk={() => {}} />,
    );
    expect(html).toContain('技术面分析师');
    expect(html).toContain('驻场 · RSI、MACD');
    expect(html).toContain('近90天命中率 70%');
    expect(html).toContain('问TA');
    expect(html).toContain('深入分析');
  });

  it('优先按 scorer_key 反查当前 tab 驻场 Agent', () => {
    expect(selectResidentAnalyst('technical', [profile])?.name).toBe('technical_agent');
  });

  it('问TA会打开 MiniChat 并预填强制 Agent mention', () => {
    useStore.setState({ draft: '', showRightPanel: false });
    openResidentAnalystChat(profile);
    expect(useStore.getState().draft).toBe('@technical_agent ');
    expect(useStore.getState().showRightPanel).toBe(true);
  });

  it.each(['Overview', 'Financial', 'Technical', 'News', 'Peers'])(
    '%sTab 顶部挂入驻场分析师栏并复用现有深挖入口',
    (tabName) => {
      const source = readFileSync(new URL(`../${tabName}Tab.tsx`, import.meta.url), 'utf8');
      expect(source).toContain("import { ResidentAnalystBar } from './shared/ResidentAnalystBar';");
      expect(source).toContain('<ResidentAnalystBar');
      expect(source).toContain('onDeepDive={() => deepDive.startDeepDive()}');
    },
  );
});

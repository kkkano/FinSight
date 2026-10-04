import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { ReportIR } from '../../types';
import { ToastProvider } from '../ui';
import { ReportHeader } from './ReportHeader';
import { getReportPresentation } from './ReportPresentation';
import { buildEvidenceBadges, buildSourceSummary } from './ReportUtils';
import { ReportView } from './ReportView';

const partialReport: ReportIR = {
  report_id: 'report-partial', ticker: 'IBM', company_name: 'IBM', title: 'IBM 分析报告',
  summary: '证据不足，无法形成总判断。', sentiment: 'neutral', confidence_score: 0.45,
  generated_at: '2026-10-04T07:03:00Z', sections: [],
  synthesis_report: '## 财务\n\n营业收入同比增长 5%，这是本轮已获取的事实。\n\n## 缺失\n\n尚缺估值判断。',
  citations: [{ source_id: 'ev-1', title: 'IBM 季度披露', url: 'https://www.ibm.com/investor/quarterly',
    snippet: '营业收入同比增长 5%', confidence: 0.7 }],
  report_quality: {
    state: 'warn', answer_status: 'partial', has_supported_content: true, publishable: true,
    reasons: [{ code: 'missing_overall_conclusion', severity: 'warn', metric: '', message: 'missing_overall_conclusion' }],
    missing_requirements: [{ subject: 'IBM', evidence_kind: 'valuation_context' }],
    metrics: { coverage: 1.0, unique_sources: 52 },
  },
};

const renderReport = (report: ReportIR, readOnly = false) => renderToStaticMarkup(
  <ToastProvider><ReportView report={report} readOnly={readOnly} /></ToastProvider>,
);

const renderHeader = (report: ReportIR, fullscreen: boolean) => renderToStaticMarkup(
  <ReportHeader report={report} formattedDate="2026-10-04" evidenceBadges={buildEvidenceBadges(report.citations)}
    sourceSummary={buildSourceSummary(report.citations)} reportHints={{}} warningNode={null} fullscreen={fullscreen} />,
);

describe('报告判断与完整度展示', () => {
  it('部分报告在卡片、只读和全屏中显示无法判断，并保留事实与来源', () => {
    for (const html of [renderReport(partialReport), renderReport(partialReport, true), renderHeader(partialReport, true)]) {
      expect(html).toContain('无法判断');
      expect(html).toContain('部分完成');
      expect(html).toContain('IBM：估值');
      expect(html).not.toContain('NEUTRAL');
      expect(html).not.toContain('>neutral<');
      expect(html).not.toContain('>中性<');
      expect(html).not.toContain('45%');
      expect(html).not.toContain('70%');
      expect(html).not.toContain('Evidence Medium');
      expect(html).not.toContain('质量门控拦截');
    }
    const html = renderReport(partialReport);
    expect(html).toContain('营业收入同比增长 5%');
    expect(html).toContain('IBM 季度披露');
    expect(html).toContain('https://www.ibm.com/investor/quarterly');
    expect(html.indexOf('IBM：估值')).toBeLessThan(html.indexOf('综合研究报告'));
  });

  it('序列化后的历史报告得到同样的状态与正文，不修改权威正文', () => {
    const restored = JSON.parse(JSON.stringify(partialReport)) as ReportIR;
    expect(renderReport(restored, true)).toBe(renderReport(partialReport, true));
    expect(restored.synthesis_report).toBe(partialReport.synthesis_report);
  });

  it('受支持的中性结论保留中性，单项缺口不会阻断整份报告', () => {
    const report: ReportIR = { ...partialReport, summary: '现金流改善与估值压力相互抵消，总体维持中性。',
      report_quality: { ...partialReport.report_quality!, conclusion_status: 'supported', reasons: [] } };
    for (const html of [renderReport(report), renderHeader(report, false), renderHeader(report, true)]) {
      expect(html).toContain('中性');
      expect(html).toContain('部分完成');
      expect(html).not.toContain('无法判断');
      expect(html).not.toContain('45%');
    }
  });

  it('兼容旧报告的质量原因、空结构化结论和精确兜底摘要', () => {
    const reasonOnly = { ...partialReport, summary: '已收集财务事实，尚有研究缺口。' };
    const structureOnly = { ...partialReport, summary: '已收集财务事实。', report_quality: undefined,
      meta: { research_synthesis: { overall_conclusion: null } } };
    const summaryOnly = { ...partialReport, report_quality: undefined };
    for (const report of [reasonOnly, structureOnly, summaryOnly]) {
      expect(getReportPresentation(report).judgmentLabel).toBe('无法判断');
    }
    expect(getReportPresentation({ ...summaryOnly, summary: '估值合理，维持中性；短期涨跌无法判断。' }).judgmentLabel).toBe('中性');
  });

  it('不把 answered 或满引用覆盖率置于未答事项之上', () => {
    const report = { ...partialReport, report_quality: { ...partialReport.report_quality!, state: 'pass' as const,
      answer_status: 'answered' as const, reasons: [], conclusion_status: 'supported' as const },
    summary: '整体维持中性。' };
    expect(getReportPresentation(report).answerStatus).toBe('partial');
    const html = renderReport(report);
    expect(html).toContain('部分完成');
    expect(html).not.toContain('质量验证通过');
  });

  it('无可用内容时显示无法判断，且不伪装成已回答', () => {
    const report = { ...partialReport, report_quality: { ...partialReport.report_quality!,
      has_supported_content: false, answer_status: 'unavailable' as const } };
    expect(getReportPresentation(report).judgmentLabel).toBe('无法判断');
    expect(renderReport(report)).toContain('无法回答');
  });

  it('接纳后端 unknown/null 合同且不再回填中性或零置信度', () => {
    const report: ReportIR = { ...partialReport, sentiment: 'unknown', confidence_score: null,
      summary: '已保留可核查的财务事实。',
      citations: partialReport.citations.map((citation) => ({ ...citation, confidence: null })),
      report_quality: { ...partialReport.report_quality!, reasons: [], conclusion_status: 'unavailable', confidence_status: 'uncalibrated' } };
    for (const html of [renderReport(report), renderHeader(report, true)]) {
      expect(html).toContain('无法判断');
      expect(html).toContain('部分完成');
      expect(html).not.toContain('>中性<');
      expect(html).not.toContain('0%');
      expect(html).not.toContain('NaN');
    }
  });

  it('老报告从 meta 恢复质量状态，明确 block 仍保留质量拦截标记', () => {
    const report: ReportIR = { ...partialReport, report_quality: undefined,
      meta: { report_quality: { state: 'block', answer_status: 'blocked', reasons: [] } } };
    expect(getReportPresentation(report).answerStatus).toBe('blocked');
    const html = renderReport(report);
    expect(html).toContain('质量门控拦截');
    expect(html).toContain('无法判断');
  });

  it('证据徽章统计可打开的去重来源，不从默认 confidence 推出可信度', () => {
    const badges = buildEvidenceBadges([
      ...partialReport.citations, { ...partialReport.citations[0], source_id: 'duplicate' },
      { source_id: 'internal', title: '内部记录', url: 'internal://agent', snippet: '', confidence: 1 },
      { source_id: 'placeholder', title: '占位', url: '#', snippet: '', confidence: 1 },
    ]);
    expect(badges.quality.label).toBe('可追溯来源 1 条');
    expect(badges.quality.label).not.toContain('%');
  });
});

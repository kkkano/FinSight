import type { ReportIR, ReportQuality, Sentiment } from '../../types';

const SENTIMENT_LABELS: Record<Exclude<Sentiment, 'unknown'>, string> = {
  bullish: '看多',
  bearish: '看空',
  neutral: '中性',
};

const MISSING_CONCLUSION_CODES = new Set([
  'missing_overall_conclusion',
  'no_supported_report_claims',
  'no_supported_content',
]);

const REQUIREMENT_LABELS: Record<string, string> = {
  price: '报价',
  price_context: '报价',
  market_session: '交易时段',
  valuation: '估值',
  valuation_context: '估值',
  financial: '财务',
  financial_context: '财务',
  filing_context: '披露材料',
  business: '业务',
  competition: '竞争',
  news: '新闻',
  news_context: '新闻',
  catalysts: '催化事件',
  risk: '风险',
  risk_context: '风险',
  overall_conclusion: '总体结论',
};

export const formatMissingRequirement = (requirement: string | Record<string, unknown>): string => {
  if (typeof requirement === 'string') return REQUIREMENT_LABELS[requirement] || requirement;
  const description = [requirement.label, requirement.message, requirement.description, requirement.requirement]
    .find((value): value is string => typeof value === 'string' && value.trim().length > 0);
  const dimension = String(requirement.dimension || requirement.evidence_kind || requirement.kind || '');
  const label = description || REQUIREMENT_LABELS[dimension] || dimension || '请求事项尚未满足';
  const subject = typeof requirement.subject === 'string' ? requirement.subject.trim() : '';
  return subject ? `${subject}：${label}` : label;
};

export const qualityHasMissingConclusion = (quality?: ReportQuality | null): boolean =>
  quality?.conclusion_status === 'unavailable'
  || (quality?.reasons || []).some((reason) => MISSING_CONCLUSION_CODES.has(reason.code.toLowerCase()));

export const getQualityAnswerStatus = (quality?: ReportQuality | null): ReportQuality['answer_status'] => {
  if (!quality) return undefined;
  if (quality.content_contract_version === 'research_content.v2' && quality.content_status) return quality.content_status;
  if (quality.answer_status === 'unavailable' || quality.has_supported_content === false) return 'unavailable';
  if (quality.answer_status === 'blocked' || ['block', 'soft_blocked', 'soft_block'].includes(quality.state)) return 'blocked';
  if (quality.answer_status === 'partial' || quality.missing_requirements?.length || qualityHasMissingConclusion(quality)) return 'partial';
  return quality.answer_status;
};

const isLegacyMissingSummary = (summary: string): boolean =>
  /^(?:证据不足[，,：:]?\s*无法形成总判断|本轮结果未通过内部一致性校验|报告暂不可用|无法判断)[。.!！\s]*$/.test(summary);

/** 同一份报告在卡片、全屏和历史回放中使用相同的判断依据；缺失结论不能解释为中性。 */
export const getReportPresentation = (report: ReportIR) => {
  const quality = report.report_quality || (report.meta?.report_quality as ReportQuality | undefined);
  const synthesis = report.meta?.research_synthesis || report.artifacts?.research_synthesis;
  const structuredOverall = synthesis && typeof synthesis === 'object' && 'overall_conclusion' in synthesis
    ? synthesis.overall_conclusion
    : undefined;
  const hasStructuredOverall = structuredOverall === undefined
    ? undefined
    : typeof structuredOverall === 'string' && structuredOverall.trim().length > 0;
  const summary = (report.summary || '').trim();
  let answerStatus = getQualityAnswerStatus(quality);
  const unavailable = qualityHasMissingConclusion(quality)
    || answerStatus === 'blocked'
    || answerStatus === 'unavailable'
    || hasStructuredOverall === false
    || (!summary && !hasStructuredOverall)
    || isLegacyMissingSummary(summary);
  const sentiment = !unavailable && report.sentiment !== 'unknown' && report.sentiment in SENTIMENT_LABELS ? report.sentiment : null;

  if (unavailable && answerStatus !== 'blocked' && answerStatus !== 'unavailable' && quality && !quality.content_status) answerStatus = 'partial';
  const answerLabel = answerStatus === 'answered' ? '已回答'
    : answerStatus === 'partial' ? '部分完成'
      : answerStatus === 'blocked' ? '未通过质量检查'
        : answerStatus === 'unavailable' ? '无法回答' : answerStatus === 'clarification_required' ? '需要补充信息' : '完整度未评估';

  return {
    quality: quality ? { ...quality, answer_status: answerStatus } : undefined,
    sentiment,
    judgmentLabel: sentiment ? SENTIMENT_LABELS[sentiment] : '无法判断',
    summary: unavailable
      ? answerStatus === 'blocked' ? '当前结果未通过质量检查，无法给出总体判断。'
        : quality?.has_supported_content === false ? '当前没有足够的已验证内容支持总体判断。'
          : '现有证据不足以形成总体判断，已获取的事实与来源见下文。'
      : summary || String(structuredOverall),
    answerStatus,
    answerLabel,
  };
};

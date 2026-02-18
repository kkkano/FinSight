/**
 * KeyInsightsCard - Top 3 key insights for the active asset.
 *
 * Without report: auto-generates insights from valuation + technicals.
 * With report: shows top 3 core_viewpoints from the report.
 */
import { useMemo } from 'react';

import type { ValuationData, TechnicalData, NewsItem } from '../../../../types/dashboard';
import type { LatestReportData } from '../../../../hooks/useLatestReport';
import { CardInfoTip } from '../../../ui/CardInfoTip';

// --- Props ---

interface KeyInsightsCardProps {
  valuation?: ValuationData | null;
  technicals?: TechnicalData | null;
  news?: NewsItem[];
  reportData?: LatestReportData | null;
  /** AI insight key points from DigestAgent — highest priority when available */
  insightPoints?: string[];
}

// --- Helpers ---

function generateAutoInsights(
  valuation: ValuationData | null | undefined,
  technicals: TechnicalData | null | undefined,
  news: NewsItem[] | undefined,
): string[] {
  const insights: string[] = [];

  // PE insight
  const pe = valuation?.trailing_pe;
  if (pe != null) {
    const comparison = pe > 25 ? '高于' : pe < 15 ? '低于' : '接近';
    insights.push(`市盈率 (${pe.toFixed(1)}) ${comparison}市场平均水平`);
  }

  // MA crossover insight
  const ma20 = technicals?.ma20;
  const ma50 = technicals?.ma50;
  if (ma20 != null && ma50 != null) {
    const cross = ma20 > ma50 ? '金叉' : '死叉';
    insights.push(`MA20/MA50 呈现${cross}形态`);
  }

  // News sentiment insight
  const newsCount = news?.length ?? 0;
  if (newsCount > 0) {
    const positive = news!.filter(
      (n) => (n.impact_score ?? 0) > 0.5,
    ).length;
    const negative = news!.filter(
      (n) => (n.impact_score ?? 0) < -0.5,
    ).length;
    insights.push(`近期 ${newsCount} 条新闻中, ${positive} 条正面 / ${negative} 条负面`);
  }

  // RSI insight
  if (insights.length < 3) {
    const rsi = technicals?.rsi;
    if (rsi != null) {
      const state = rsi > 70 ? '超买区间' : rsi < 30 ? '超卖区间' : '正常区间';
      insights.push(`RSI (${rsi.toFixed(1)}) 处于${state}`);
    }
  }

  // Beta insight
  if (insights.length < 3) {
    const beta = valuation?.beta;
    if (beta != null) {
      const level = beta > 1.5 ? '较高' : beta < 0.8 ? '较低' : '适中';
      insights.push(`Beta (${beta.toFixed(2)}) 波动性${level}`);
    }
  }

  return insights.slice(0, 3);
}

function extractReportInsights(reportData: LatestReportData | null | undefined): string[] | null {
  if (!reportData?.report) return null;
  const report = reportData.report as Record<string, unknown>;
  const viewpoints = report.core_viewpoints;
  if (!Array.isArray(viewpoints)) return null;

  return viewpoints
    .slice(0, 3)
    .map((vp: unknown) => {
      if (typeof vp === 'string') return vp;
      if (typeof vp === 'object' && vp !== null) {
        const obj = vp as Record<string, unknown>;
        return String(obj.title ?? obj.content ?? obj.text ?? '');
      }
      return '';
    })
    .filter((s) => s.length > 0);
}

// --- Component ---

export function KeyInsightsCard({ valuation, technicals, news, reportData, insightPoints }: KeyInsightsCardProps) {
  const insights = useMemo(() => {
    // Priority: AI insight > report > auto-generated
    if (insightPoints && insightPoints.length > 0) return insightPoints.slice(0, 5);
    const reportInsights = extractReportInsights(reportData);
    if (reportInsights && reportInsights.length > 0) return reportInsights;
    return generateAutoInsights(valuation, technicals, news);
  }, [valuation, technicals, news, reportData, insightPoints]);

  return (
    <div className="flex flex-col p-4 bg-fin-card rounded-xl border border-fin-border">
      <div className="flex items-center gap-1 text-xs font-medium text-fin-muted mb-3">
        关键洞察
        <CardInfoTip content="优先级：AI 洞察 > 研报核心观点 > 规则自动生成" />
      </div>

      {insights.length === 0 ? (
        <div className="text-sm text-fin-muted">--</div>
      ) : (
        <ul className="space-y-2">
          {insights.map((insight, idx) => (
            <li key={idx} className="flex items-start gap-2">
              <span className="w-5 h-5 rounded-full bg-fin-primary/10 text-fin-primary text-2xs flex items-center justify-center shrink-0 mt-0.5">
                {idx + 1}
              </span>
              <span className="text-sm text-fin-text leading-relaxed">{insight}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default KeyInsightsCard;

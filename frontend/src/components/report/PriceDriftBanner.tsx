import React, { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { apiClient } from '../../api/client';

/**
 * P2-11 报告与实时价差提示。
 *
 * 投资报告生成需要几分钟，报告里的价格是生成时刻的快照。用户可能在几小时甚至
 * 几天后查看（历史/缓存命中），拿过时价格做决策有风险。本组件在报告渲染后异步
 * 拉取实时价，与报告价格对比，显著（价差超阈值或报告超 24h）时显示琥珀提示。
 *
 * 诚实原则：
 * - 实时价拿不到 → 后端返回 current_price=null，仅在报告超时时显示「时效提示」。
 * - reportPrice 缺失 → 只做时效提示，不编造价差。
 * - significant=false → 不渲染，避免噪音。
 */

export interface PriceDriftBannerProps {
  ticker?: string;
  /** 报告生成时刻的价格快照；缺失时只做时效提示 */
  reportPrice?: number | null;
  /** 报告生成时间（ISO8601），用于计算时效 */
  reportGeneratedAt?: string;
}

export interface PriceDriftResult {
  ticker: string;
  report_price: number | null;
  current_price: number | null;
  drift_pct: number | null;
  report_age_hours: number | null;
  threshold_pct: number;
  significant: boolean;
}

/** 把小时数格式化为更友好的中文表达（>=48h 时用「天」）。 */
const formatAge = (hours: number): string => {
  if (hours >= 48) {
    const days = Math.floor(hours / 24);
    return `${days} 天前`;
  }
  return `${Math.round(hours)} 小时前`;
};

/** 价差百分比带符号格式化，如 +5.0% / -3.2%。 */
const formatDrift = (pct: number): string => `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;

/**
 * 纯展示组件（无副作用），接收已解析的价差结果。
 * 拆出独立组件便于做 SSR(renderToStaticMarkup) 单元测试。
 */
export const PriceDriftBannerView: React.FC<{ result: PriceDriftResult | null }> = ({ result }) => {
  // 不显著 / 无结果 → 不渲染（避免噪音）
  if (!result || !result.significant) return null;

  const { report_price, current_price, drift_pct, report_age_hours } = result;
  const hasPriceComparison =
    typeof report_price === 'number' &&
    report_price > 0 &&
    typeof current_price === 'number' &&
    typeof drift_pct === 'number';
  const ageText = typeof report_age_hours === 'number' ? formatAge(report_age_hours) : '较早';

  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-200 bg-amber-50/90 px-4 py-3 text-xs leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-900/20 dark:text-amber-200"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle size={15} className="mt-0.5 shrink-0" />
        <div>
          {hasPriceComparison ? (
            <span className="font-medium">
              本报告生成于 {ageText}（价格 ${report_price!.toFixed(2)}），当前价格 $
              {current_price!.toFixed(2)}（变动 {formatDrift(drift_pct!)}），结论可能需要重新评估。
            </span>
          ) : (
            <span className="font-medium">
              本报告生成于 {ageText}，市场行情可能已发生变化，请结合最新价格重新评估结论。
            </span>
          )}
        </div>
      </div>
    </div>
  );
};

export const PriceDriftBanner: React.FC<PriceDriftBannerProps> = ({
  ticker,
  reportPrice,
  reportGeneratedAt,
}) => {
  const [result, setResult] = useState<PriceDriftResult | null>(null);

  useEffect(() => {
    let mounted = true;
    setResult(null);

    // 没有 ticker 就没法查价差，直接跳过
    if (!ticker) return;

    apiClient
      .checkPriceDrift({
        ticker,
        reportPrice: reportPrice ?? undefined,
        reportGeneratedAt,
      })
      .then((res) => {
        if (mounted) setResult(res);
      })
      .catch(() => {
        // 接口失败时静默降级：不显示价差提示，不打扰用户
        if (mounted) setResult(null);
      });

    return () => {
      mounted = false;
    };
  }, [ticker, reportPrice, reportGeneratedAt]);

  return <PriceDriftBannerView result={result} />;
};

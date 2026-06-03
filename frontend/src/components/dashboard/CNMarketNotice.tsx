/**
 * CNMarketNotice - A股交易制度提示条（P2-10 A股体验补齐，子任务 D）。
 *
 * 当当前标的为 A股（.SS / .SZ / .BJ）时，在 Dashboard 主视图展示一条轻量
 * 制度提示，帮助习惯美股 T+0 的用户理解 A股的 T+1 与涨跌停限制。
 * 用户可关闭（关闭状态仅在当前会话生效，不做持久化）。
 */
import { useState } from 'react';
import { Info, X } from 'lucide-react';

import { isAShareTicker } from '../../utils/format';

interface CNMarketNoticeProps {
  ticker: string | null | undefined;
}

export function CNMarketNotice({ ticker }: CNMarketNoticeProps) {
  const [dismissed, setDismissed] = useState(false);

  // 非 A股标的不渲染；用户已关闭则不渲染
  if (!isAShareTicker(ticker) || dismissed) return null;

  return (
    <div
      data-testid="cn-market-notice"
      className="flex items-center gap-2 px-5 py-1.5 bg-fin-primary/5 border-b border-fin-border text-2xs text-fin-muted shrink-0 max-lg:px-3"
    >
      <Info size={12} className="text-fin-primary shrink-0" />
      <span className="min-w-0 flex-1 leading-snug">
        <span className="font-medium text-fin-text">A股交易制度：</span>
        T+1（当日买入次日才能卖出） · 涨跌停限制 ±10%（ST 股 ±5%，科创板/创业板 ±20%）
      </span>
      <button
        type="button"
        aria-label="关闭提示"
        onClick={() => setDismissed(true)}
        className="p-1 rounded text-fin-muted hover:text-fin-text hover:bg-fin-hover transition-colors shrink-0"
      >
        <X size={12} />
      </button>
    </div>
  );
}

export default CNMarketNotice;

/**
 * AiDisclaimer -- 全局常驻 AI 免责声明（P0-3）
 * 所有展示 AI 分析内容的页面必须挂载。
 *
 * 职责边界：本组件渲染前端固定的通用免责文案；
 * workbench/rebalance/DisclaimerBanner 渲染后端 payload 传入的动态调仓免责文案，两者不可互换。
 *
 * 色板说明：使用标准 amber 色板而非 fin-warning token，
 * 因 fin-* hex 变量带 Tailwind alpha 修饰符（如 /10）在暗色模式下会失效。
 */
import React from 'react';
import { AlertTriangle } from 'lucide-react';

interface AiDisclaimerProps {
  /** compact: 单行小字（页面底部）；banner: 醒目横幅（页面顶部） */
  variant?: 'compact' | 'banner';
}

export const AiDisclaimer: React.FC<AiDisclaimerProps> = ({ variant = 'compact' }) => {
  if (variant === 'banner') {
    return (
      <div
        role="note"
        className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg border border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-700/50 dark:bg-amber-900/20 dark:text-amber-200"
      >
        <AlertTriangle size={14} className="shrink-0" aria-hidden />
        <span>本页内容由 AI 生成，仅供研究参考，不构成投资建议。市场有风险，决策需谨慎。</span>
      </div>
    );
  }
  return (
    <p className="text-center text-xs text-fin-muted">
      AI 生成内容可能存在误差 · 仅供研究参考 · 不构成投资建议
    </p>
  );
};

export default AiDisclaimer;

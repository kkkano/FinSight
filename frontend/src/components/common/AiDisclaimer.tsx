/**
 * AiDisclaimer -- 全局常驻 AI 免责声明（P0-3）
 * 所有展示 AI 分析内容的页面必须挂载。
 */
import React from 'react';

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
        <span aria-hidden>⚠️</span>
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

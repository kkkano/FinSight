/**
 * EmptyState — 带动作的空状态（08 设计语言）。
 * 规范：每个空状态必须给用户一个下一步动作，禁止裸"暂无数据"。
 */
import type { ComponentType, ReactNode } from 'react';

interface EmptyStateProps {
  /** lucide 图标组件，如 Inbox / FileSearch */
  icon?: ComponentType<{ size?: number | string; className?: string }>;
  message: string;
  /** 主操作：文案 + 回调。约定必填（除非纯装饰场景显式传 null） */
  action?: { label: string; onClick: () => void } | null;
  children?: ReactNode;
  className?: string;
}

export function EmptyState({ icon: Icon, message, action, children, className = '' }: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center gap-2 py-8 text-center ${className}`.trim()}>
      {Icon && <Icon size={20} className="text-t-text3" />}
      <p className="text-sm text-t-text2">{message}</p>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="h-8 px-3 rounded-md border border-t-border text-[13px] text-t-text2 hover:border-t-accent/60 hover:text-t-text transition-colors"
        >
          {action.label}
        </button>
      )}
      {children}
    </div>
  );
}

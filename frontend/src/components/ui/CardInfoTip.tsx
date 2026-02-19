/**
 * CardInfoTip — Small info icon with hover tooltip for dashboard cards.
 *
 * Shows an ℹ️ icon in the card header area. On hover, displays a tooltip
 * explaining the data source or calculation method. Supports multi-line
 * content via whitespace-normal + max-width.
 */
import { AlertCircle, Info } from 'lucide-react';
import type { ReactNode } from 'react';

interface CardInfoTipProps {
  /** Tooltip content — supports ReactNode for rich formatting */
  content: ReactNode;
  /** Icon size in pixels (default 12) */
  size?: number;
  /** Icon style variant */
  icon?: 'info' | 'alert';
  /** Additional CSS classes on the wrapper */
  className?: string;
  /** Optional test id for E2E */
  testId?: string;
}

export function CardInfoTip({
  content,
  size = 12,
  icon = 'info',
  className = '',
  testId,
}: CardInfoTipProps) {
  const Icon = icon === 'alert' ? AlertCircle : Info;
  const iconClassName = icon === 'alert'
    ? 'text-fin-warning/70 group-hover/tip:text-fin-warning'
    : 'text-fin-muted/50 group-hover/tip:text-fin-muted';

  return (
    <span className={`relative inline-flex group/tip ${className}`} data-testid={testId}>
      <Icon
        size={size}
        className={`${iconClassName} transition-colors cursor-help`}
        aria-hidden="true"
      />
      <span
        role="tooltip"
        className="pointer-events-none absolute right-0 top-full mt-1.5
          w-max max-w-[220px] whitespace-normal rounded-md border border-fin-border
          bg-fin-panel px-2.5 py-1.5 text-2xs text-fin-text leading-relaxed
          opacity-0 shadow-md transition-opacity z-30
          group-hover/tip:opacity-100 group-focus-within/tip:opacity-100"
      >
        {content}
      </span>
    </span>
  );
}

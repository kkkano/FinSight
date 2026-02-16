import type { ReactNode } from 'react';

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Tooltip({ content, children, className = '' }: TooltipProps) {
  return (
    <span className={`relative inline-flex group ${className}`}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full mt-1.5 -translate-x-1/2 whitespace-nowrap rounded-md border border-fin-border bg-fin-panel px-2 py-1 text-2xs text-fin-text opacity-0 shadow-md transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 z-20"
      >
        {content}
      </span>
    </span>
  );
}

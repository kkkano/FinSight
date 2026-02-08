import { type HTMLAttributes } from 'react';

type BadgeVariant = 'default' | 'success' | 'danger' | 'warning' | 'info';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-fin-bg-secondary text-fin-text-secondary',
  success: 'bg-emerald-500/10 text-fin-success',
  danger: 'bg-red-500/10 text-fin-danger',
  warning: 'bg-amber-500/10 text-fin-warning',
  info: 'bg-fin-primary/10 text-fin-primary',
};

function Badge({ variant = 'default', className = '', children, ...props }: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center px-1.5 py-0.5 text-2xs font-medium rounded-md
        ${variantClasses[variant]} ${className}
      `.trim()}
      {...props}
    >
      {children}
    </span>
  );
}

export { Badge };
export type { BadgeProps, BadgeVariant };

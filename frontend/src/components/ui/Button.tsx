import { type ButtonHTMLAttributes, forwardRef } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-fin-primary text-white hover:bg-fin-primary/90 focus-visible:ring-fin-primary/50',
  secondary: 'border border-fin-border bg-fin-card text-fin-text hover:bg-fin-hover focus-visible:ring-fin-primary/30',
  ghost: 'text-fin-text-secondary hover:bg-fin-hover hover:text-fin-text focus-visible:ring-fin-primary/30',
  danger: 'bg-fin-danger text-white hover:opacity-90 focus-visible:ring-fin-danger/50',
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1 text-xs rounded-lg',
  md: 'px-3.5 py-1.5 text-sm rounded-lg',
  lg: 'px-5 py-2.5 text-sm rounded-lg',
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'secondary', size = 'md', className = '', disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled}
      className={`
        inline-flex items-center justify-center gap-1.5 font-medium
        transition-colors duration-150
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1
        disabled:opacity-50 disabled:pointer-events-none
        ${variantClasses[variant]} ${sizeClasses[size]} ${className}
      `.trim()}
      {...props}
    >
      {children}
    </button>
  )
);
Button.displayName = 'Button';

export { Button };
export type { ButtonProps, ButtonVariant, ButtonSize };

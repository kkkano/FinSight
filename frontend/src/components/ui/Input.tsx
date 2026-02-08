import { type InputHTMLAttributes, forwardRef } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, className = '', id, ...props }, ref) => {
    const inputId = id || (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined);
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label htmlFor={inputId} className="text-xs font-medium text-fin-text-secondary">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={`
            w-full px-3 py-1.5 text-sm
            bg-fin-bg border border-fin-border rounded-lg
            text-fin-text placeholder:text-fin-muted
            transition-colors duration-150
            focus:outline-none focus:border-fin-primary focus:ring-1 focus:ring-fin-primary/30
            disabled:opacity-50 disabled:cursor-not-allowed
            ${className}
          `.trim()}
          {...props}
        />
      </div>
    );
  }
);
Input.displayName = 'Input';

export { Input };
export type { InputProps };

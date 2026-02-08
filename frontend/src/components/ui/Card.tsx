import { type HTMLAttributes, forwardRef } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  hoverable?: boolean;
}

const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ hoverable = false, className = '', children, ...props }, ref) => (
    <div
      ref={ref}
      className={`
        border border-fin-border rounded-xl bg-fin-card
        ${hoverable ? 'transition-colors duration-150 hover:bg-fin-hover cursor-pointer' : ''}
        ${className}
      `.trim()}
      {...props}
    >
      {children}
    </div>
  )
);
Card.displayName = 'Card';

export { Card };
export type { CardProps };

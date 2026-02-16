export interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  lines?: number;
}

export function Skeleton({
  className = '',
  variant = 'text',
  lines = 1,
}: SkeletonProps) {
  const baseClass = 'animate-pulse bg-fin-border';

  if (variant === 'circular') {
    return <div className={`${baseClass} rounded-full ${className}`.trim()} />;
  }

  if (variant === 'rectangular') {
    return <div className={`${baseClass} rounded-lg ${className}`.trim()} />;
  }

  const count = Math.max(1, lines);
  return (
    <div className={`space-y-2 ${className}`.trim()}>
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className={`${baseClass} h-3 rounded ${index === count - 1 && count > 1 ? 'w-3/4' : 'w-full'}`}
        />
      ))}
    </div>
  );
}

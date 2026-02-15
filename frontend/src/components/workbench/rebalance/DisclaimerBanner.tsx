/**
 * DisclaimerBanner — Fixed bottom yellow banner with disclaimer text.
 *
 * Always visible and non-dismissible. Renders the disclaimer string
 * from the rebalance suggestion payload.
 */
import { AlertTriangle } from 'lucide-react';

interface DisclaimerBannerProps {
  disclaimer: string;
}

export function DisclaimerBanner({ disclaimer }: DisclaimerBannerProps) {
  return (
    <div className="flex items-start gap-2 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
      <AlertTriangle size={16} className="shrink-0 mt-0.5 text-fin-warning" />
      <p className="text-xs text-amber-600 dark:text-amber-400 leading-relaxed">
        {disclaimer}
      </p>
    </div>
  );
}

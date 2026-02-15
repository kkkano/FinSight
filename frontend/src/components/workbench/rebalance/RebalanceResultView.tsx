/**
 * RebalanceResultView — Container component that renders the full
 * rebalance suggestion result.
 *
 * Composes: SuggestionSummaryCard + ActionList + DisclaimerBanner + ActionButtons
 */
import { Card } from '../../ui/Card.tsx';
import { SuggestionSummaryCard } from './SuggestionSummaryCard.tsx';
import { ActionList } from './ActionList.tsx';
import { DisclaimerBanner } from './DisclaimerBanner.tsx';
import { ActionButtons } from './ActionButtons.tsx';
import type { RebalanceSuggestion, SuggestionStatus } from '../../../types/dashboard.ts';

interface RebalanceResultViewProps {
  suggestion: RebalanceSuggestion;
  onUpdateStatus: (id: string, status: SuggestionStatus) => Promise<void>;
  onRegenerate: () => void;
}

export function RebalanceResultView({ suggestion, onUpdateStatus, onRegenerate }: RebalanceResultViewProps) {
  return (
    <Card className="p-4 space-y-4">
      <SuggestionSummaryCard suggestion={suggestion} />

      <div className="border-t border-fin-border pt-3">
        <ActionList actions={suggestion.actions} />
      </div>

      <DisclaimerBanner disclaimer={suggestion.disclaimer} />

      <div className="border-t border-fin-border pt-3">
        <ActionButtons
          suggestion={suggestion}
          onUpdateStatus={onUpdateStatus}
          onRegenerate={onRegenerate}
        />
      </div>
    </Card>
  );
}

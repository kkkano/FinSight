import { useMemo } from 'react';

import { useAgentProfiles } from '../../../../hooks/useAgentProfiles';
import { useChatHandoff } from '../../../../hooks/useChatHandoff';
import { useDashboardStore } from '../../../../store/dashboardStore';
import {
  selectResidentAnalyst,
  type ResidentAnalystProfile,
} from './residentAnalyst';

interface ResidentAnalystBarProps {
  tab: string;
  onDeepDive: () => void;
  deepDiveRunning?: boolean;
  onAsk?: (profile: ResidentAnalystProfile) => void;
  profile?: ResidentAnalystProfile | null;
}

export function ResidentAnalystBar({
  tab,
  onDeepDive,
  deepDiveRunning = false,
  onAsk,
  profile: providedProfile,
}: ResidentAnalystBarProps) {
  const { profiles } = useAgentProfiles();
  const handoffToChat = useChatHandoff();
  const activeSymbol = useDashboardStore((state) => state.activeAsset?.symbol);

  const profile = useMemo(
    () => providedProfile ?? selectResidentAnalyst(tab, profiles),
    [profiles, providedProfile, tab],
  );
  if (!profile) return null;

  const hitRate = profile.track_record?.sample_state === 'sufficient'
    && typeof profile.track_record.hit_rate === 'number'
    ? `近90天命中率 ${(profile.track_record.hit_rate * 100).toFixed(0)}%`
    : null;

  const handleAsk = () => {
    if (onAsk) {
      onAsk(profile);
      return;
    }
    handoffToChat({
      draft: `@${profile.name} `,
      activeSymbol,
      sourceView: 'dashboard',
      sourceTab: tab,
    });
  };

  return (
    <div className="flex min-h-10 items-center gap-2 rounded-md border border-t-border bg-t-surface px-3 py-1.5" data-testid={`resident-analyst-${tab}`}>
      <span
        className="inline-flex h-6 min-w-6 items-center justify-center rounded border border-current/30 bg-t-elevated px-1 font-mono text-2xs"
        style={{ color: `var(--${profile.color_token})` }}
      >
        {profile.glyph}
      </span>
      <div className="min-w-0 flex-1 truncate text-xs text-t-text2">
        <span className="font-medium text-t-text">{profile.display_name}</span>
        <span className="ml-1 text-t-text3">驻场 · {profile.mandate}</span>
        {hitRate && <span className="num ml-2 text-t-accent">{hitRate}</span>}
      </div>
      <button type="button" className="rounded border border-t-border px-2 py-1 text-2xs text-t-text2 hover:border-t-accent/50 hover:text-t-accent" onClick={handleAsk}>
        问TA
      </button>
      <button type="button" disabled={deepDiveRunning} className="rounded border border-t-accent/40 px-2 py-1 text-2xs text-t-accent hover:bg-t-accent/10 disabled:opacity-50" onClick={onDeepDive}>
        {deepDiveRunning ? '分析中' : '深入分析'}
      </button>
    </div>
  );
}

export default ResidentAnalystBar;

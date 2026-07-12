import { useStore } from '../../../../store/useStore';
import type { AgentProfileView } from '../../../../types/agents';

export type ResidentAnalystProfile = AgentProfileView;

export function selectResidentAnalyst(
  tab: string,
  profiles: ResidentAnalystProfile[],
): ResidentAnalystProfile | null {
  return profiles.find((item) => item.scorer_key === tab)
    ?? profiles.find((item) => item.dashboard_tabs?.includes(tab))
    ?? null;
}

export function openResidentAnalystChat(profile: ResidentAnalystProfile): void {
  const store = useStore.getState();
  store.setDraft(`@${profile.name} `);
  store.setShowRightPanel(true);
}

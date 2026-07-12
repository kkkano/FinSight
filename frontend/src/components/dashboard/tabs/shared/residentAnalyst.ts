import { useStore } from '../../../../store/useStore';

export interface ResidentAnalystProfile {
  name: string;
  display_name: string;
  short_zh: string;
  glyph: string;
  color_token: string;
  mandate: string;
  scorer_key?: string | null;
  dashboard_tabs?: string[];
  track_record?: { hit_rate?: number | null; sample_state?: string };
}

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

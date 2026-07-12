export interface AgentTrackRecord {
  sample_count?: number;
  hit_rate?: number | null;
  sample_state?: string;
  by_direction?: Record<string, { sample_count?: number; hit_rate?: number | null }>;
}

export interface AgentProfileView {
  name: string;
  display_name: string;
  short_zh: string;
  description: string;
  glyph: string;
  color_token: string;
  mandate: string;
  scorer_key?: string | null;
  dashboard_tabs?: string[];
  insert_text: string;
  track_record?: AgentTrackRecord;
}

export type AgentProfileMap = Record<string, AgentProfileView>;

function isAgentProfile(value: unknown): value is AgentProfileView & Record<string, unknown> {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  return typeof item.name === 'string'
    && typeof item.display_name === 'string'
    && typeof item.short_zh === 'string'
    && typeof item.description === 'string'
    && typeof item.glyph === 'string'
    && typeof item.color_token === 'string'
    && typeof item.mandate === 'string'
    && typeof item.insert_text === 'string';
}

export function parseAgentProfiles(items: unknown[]): AgentProfileView[] {
  return items.filter(isAgentProfile);
}

export function indexAgentProfiles(profiles: AgentProfileView[]): AgentProfileMap {
  return Object.fromEntries(profiles.map((profile) => [profile.name, profile]));
}

import { useEffect, useMemo, useState } from 'react';

import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';
import {
  indexAgentProfiles,
  parseAgentProfiles,
  type AgentProfileMap,
  type AgentProfileView,
} from '../types/agents';

const profileCache = new Map<string, AgentProfileView[]>();
const pendingRequests = new Map<string, Promise<AgentProfileView[]>>();

function loadAgentProfiles(cacheKey: string): Promise<AgentProfileView[]> {
  const cached = profileCache.get(cacheKey);
  if (cached) return Promise.resolve(cached);
  const pending = pendingRequests.get(cacheKey);
  if (pending) return pending;

  const request = apiClient.listAgents(undefined, 50)
    .then((response) => {
      const profiles = response?.success && Array.isArray(response.items)
        ? parseAgentProfiles(response.items)
        : [];
      profileCache.set(cacheKey, profiles);
      return profiles;
    })
    .catch(() => [])
    .finally(() => pendingRequests.delete(cacheKey));
  pendingRequests.set(cacheKey, request);
  return request;
}

export function useAgentProfiles(): { profiles: AgentProfileView[]; profilesByName: AgentProfileMap } {
  const cacheKey = useStore((state) => state.authIdentity?.userId || 'public');
  const [profiles, setProfiles] = useState<AgentProfileView[]>(() => profileCache.get(cacheKey) ?? []);

  useEffect(() => {
    let cancelled = false;
    setProfiles(profileCache.get(cacheKey) ?? []);
    void loadAgentProfiles(cacheKey).then((next) => {
      if (!cancelled) setProfiles(next);
    });
    return () => { cancelled = true; };
  }, [cacheKey]);

  return {
    profiles,
    profilesByName: useMemo(() => indexAgentProfiles(profiles), [profiles]),
  };
}

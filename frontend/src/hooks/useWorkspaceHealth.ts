import { useQuery } from '@tanstack/react-query';

import { API_BASE_URL } from '../config/runtime';
import { buildWorkspaceHealthStatus, type WorkspaceHealthStatus } from '../components/layout/workspaceHealth';

export async function fetchWorkspaceHealth(signal?: AbortSignal): Promise<WorkspaceHealthStatus> {
  const read = async (path: string) => {
    const response = await fetch(`${API_BASE_URL}${path}`, { signal });
    return { status: response.status, payload: await response.json().catch(() => null) };
  };
  const [health, capabilities] = await Promise.allSettled([read('/health'), read('/api/capabilities')]);
  if (health.status !== 'fulfilled') return buildWorkspaceHealthStatus(null);
  return buildWorkspaceHealthStatus(health.value.payload, {
    httpStatus: health.value.status,
    capabilities: capabilities.status === 'fulfilled' ? capabilities.value.payload : null,
    capabilitiesStatus: capabilities.status === 'fulfilled' ? capabilities.value.status : 503,
  });
}

export function useWorkspaceHealth() {
  return useQuery({
    queryKey: ['workspace-health'], queryFn: ({ signal }) => fetchWorkspaceHealth(signal),
    staleTime: 30_000, refetchInterval: 60_000, retry: false,
  }).data ?? null;
}

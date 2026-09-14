import type { EntryMode } from '../store/useStore';


export type ProtectedRouteAccess = 'allow' | 'pending' | 'deny';

export const resolveProtectedRouteAccess = (
  userId: string | null | undefined,
  entryMode: EntryMode,
): ProtectedRouteAccess => {
  if (String(userId || '').trim()) return 'allow';
  if (entryMode === 'pending') return 'pending';
  return 'deny';
};

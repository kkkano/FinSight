import { describe, expect, it } from 'vitest';

import { normalizePersistedEntryMode } from '../store/useStore';
import { resolveProtectedRouteAccess } from './access';


describe('authenticated route access', () => {
  it('requires a resolved user identity instead of persisted authenticated mode', () => {
    expect(resolveProtectedRouteAccess(null, 'authenticated')).toBe('deny');
    expect(resolveProtectedRouteAccess('user-1', 'authenticated')).toBe('allow');
  });

  it('keeps protected routes unmounted while Supabase restores the session', () => {
    expect(resolveProtectedRouteAccess(null, 'pending')).toBe('pending');
  });

  it('never restores authenticated authority from localStorage alone', () => {
    expect(normalizePersistedEntryMode('authenticated')).toBe('pending');
    expect(normalizePersistedEntryMode('anonymous')).toBe('anonymous');
    expect(normalizePersistedEntryMode(null)).toBe('pending');
  });
});

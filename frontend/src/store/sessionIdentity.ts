import type { AuthIdentity, EntryMode } from './stateTypes';

export const DEFAULT_USER_ID = 'default_user';

export const SESSION_PART_PATTERN = /[^A-Za-z0-9._-]/g;

export const normalizeSessionPart = (value: string, fallback: string): string => {
  const normalized = String(value || '').trim().replace(SESSION_PART_PATTERN, '-').slice(0, 64);
  return normalized || fallback;
};

export const normalizePersistedEntryMode = (raw: string | null): EntryMode =>
  raw === 'anonymous' ? 'anonymous' : 'pending';

export const getInitialEntryMode = (): EntryMode => {
  if (typeof window === 'undefined') return 'pending';
  return normalizePersistedEntryMode(window.localStorage.getItem('finsight-entry-mode'));
};

export const buildAnonymousSessionId = (): string => {
  const randomPart =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return `public:anonymous:${randomPart}`;
};

export const buildUserSessionId = (userId: string, thread: string = 'default'): string => {
  const normalizedUser = normalizeSessionPart(userId, 'user');
  const normalizedThread = normalizeSessionPart(thread, 'default');
  return `public:${normalizedUser}:${normalizedThread}`;
};

export const deriveUserIdFromSessionId = (sessionId: string | null | undefined): string => {
  const raw = (sessionId || '').trim();
  if (!raw) return DEFAULT_USER_ID;

  const parts = raw.split(':');
  if (parts.length >= 2) {
    const candidate = parts[1]?.trim();
    if (candidate) return candidate;
  }

  if (parts.length === 1) {
    return DEFAULT_USER_ID;
  }

  return DEFAULT_USER_ID;
};

export const sessionBelongsToIdentity = (
  sessionId: string | null | undefined,
  identity: AuthIdentity | null,
): boolean => {
  const parts = String(sessionId || '').trim().split(':');
  if (parts.length !== 3) return false;
  const [tenantId, ownerId] = parts;
  if (!ownerId) return false;
  if (!identity?.userId) return tenantId === 'public' && ownerId === 'anonymous';
  return ownerId === normalizeSessionPart(identity.userId, 'user');
};

export const sessionsHaveSameOwner = (left: string, right: string): boolean => {
  const leftParts = String(left || '').trim().split(':');
  const rightParts = String(right || '').trim().split(':');
  if (leftParts.length !== 3 || rightParts.length !== 3) return false;
  if (leftParts[1] === 'anonymous' || rightParts[1] === 'anonymous') {
    return leftParts[0] === 'public'
      && rightParts[0] === 'public'
      && leftParts[1] === rightParts[1];
  }
  return Boolean(leftParts[1] && leftParts[1] === rightParts[1]);
};

export const getInitialSessionId = (): string | null => {
  if (typeof window === 'undefined') return null;
  const raw = window.localStorage.getItem('finsight-session-id');
  if (!raw) {
    const generated = buildAnonymousSessionId();
    window.localStorage.setItem('finsight-session-id', generated);
    return generated;
  }
  const trimmed = raw.trim();
  if (!trimmed) {
    const generated = buildAnonymousSessionId();
    window.localStorage.setItem('finsight-session-id', generated);
    return generated;
  }
  return trimmed;
};

export const buildNewConversationSessionId = (identity: AuthIdentity | null): string => {
  if (identity?.userId) {
    const thread = `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    return buildUserSessionId(identity.userId, thread);
  }
  return buildAnonymousSessionId();
};

export const ownedSessionOrFallback = (
  sessionId: string | null | undefined,
  identity: AuthIdentity | null,
): string => {
  const candidate = String(sessionId || '').trim();
  if (candidate && sessionBelongsToIdentity(candidate, identity)) return candidate;
  return identity?.userId ? buildUserSessionId(identity.userId) : buildAnonymousSessionId();
};

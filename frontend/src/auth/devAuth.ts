import type { AuthIdentity } from '../store/useStore';
import {
  RAG_INSPECTOR_DEV_ACCESS_TOKEN,
  RAG_INSPECTOR_DEV_AUTH_ENABLED,
  RAG_INSPECTOR_DEV_EMAIL,
  RAG_INSPECTOR_DEV_STORAGE_KEY,
  RAG_INSPECTOR_DEV_USER_ID,
} from '../config/runtime';

export const isRagInspectorDevAuthAvailable = (): boolean => Boolean(RAG_INSPECTOR_DEV_AUTH_ENABLED && RAG_INSPECTOR_DEV_ACCESS_TOKEN);

export const isRagInspectorDevAuthActive = (): boolean => {
  if (typeof window === 'undefined') return false;
  return isRagInspectorDevAuthAvailable() && window.localStorage.getItem(RAG_INSPECTOR_DEV_STORAGE_KEY) === '1';
};

export const setRagInspectorDevAuthActive = (active: boolean): void => {
  if (typeof window === 'undefined') return;
  if (active) {
    window.localStorage.setItem(RAG_INSPECTOR_DEV_STORAGE_KEY, '1');
    return;
  }
  window.localStorage.removeItem(RAG_INSPECTOR_DEV_STORAGE_KEY);
};

export const getRagInspectorDevAccessToken = (): string | null => {
  if (!isRagInspectorDevAuthActive()) return null;
  return RAG_INSPECTOR_DEV_ACCESS_TOKEN;
};

export const verifyRagInspectorDevAccessPassword = (candidate: string): boolean => {
  if (!isRagInspectorDevAuthAvailable()) return false;
  return String(candidate || '').trim() === String(RAG_INSPECTOR_DEV_ACCESS_TOKEN || '').trim();
};

export const getRagInspectorDevIdentity = (): AuthIdentity | null => {
  if (!isRagInspectorDevAuthAvailable()) return null;
  return {
    userId: RAG_INSPECTOR_DEV_USER_ID,
    email: RAG_INSPECTOR_DEV_EMAIL,
  };
};

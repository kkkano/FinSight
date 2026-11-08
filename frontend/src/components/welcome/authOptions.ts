import { SUPABASE_AUTH_ENABLED } from '../../config/runtime';

export const githubLoginEnabled = (): boolean => SUPABASE_AUTH_ENABLED
  && String(import.meta.env.VITE_GITHUB_AUTH_ENABLED).toLowerCase() === 'true';

export function safeLoginDestination(from: string | null): string {
  const value = String(from || '').trim();
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\') || value.startsWith('/welcome')) return '/dashboard/AAPL';
  return value;
}


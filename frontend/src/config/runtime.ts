const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';

const normalizeBaseUrl = (value: string): string => value.replace(/\/+$/, '');
const resolveOptionalEnv = (value: string | undefined): string | null => {
  const raw = String(value || '').trim();
  return raw || null;
};

const resolveApiBaseUrl = (): string => {
  const raw = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  if (!raw) return DEFAULT_API_BASE_URL;
  return normalizeBaseUrl(raw);
};

export const API_BASE_URL = resolveApiBaseUrl();
export const SUPABASE_URL = resolveOptionalEnv(import.meta.env.VITE_SUPABASE_URL as string | undefined);
export const SUPABASE_PUBLISHABLE_KEY = resolveOptionalEnv(
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined,
);
export const SUPABASE_AUTH_ENABLED = Boolean(SUPABASE_URL && SUPABASE_PUBLISHABLE_KEY);

export const buildApiUrl = (path: string): string => {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
};

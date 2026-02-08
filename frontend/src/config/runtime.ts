const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';

const normalizeBaseUrl = (value: string): string => value.replace(/\/+$/, '');

const resolveApiBaseUrl = (): string => {
  const raw = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  if (!raw) return DEFAULT_API_BASE_URL;
  return normalizeBaseUrl(raw);
};

export const API_BASE_URL = resolveApiBaseUrl();

export const buildApiUrl = (path: string): string => {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
};


import type { RawSSEEvent } from '../../types';

// Sensitive key fragments to redact on export
const EXPORT_SENSITIVE_KEY_FRAGMENTS = [
  'api_key',
  'apikey',
  'authorization',
  'token',
  'cookie',
  'secret',
  'password',
  'set-cookie',
];

const maskSecret = (value: string): string => {
  const text = String(value || '');
  if (!text) return '***';
  if (text.length <= 8) return '***';
  return `${text.slice(0, 3)}***${text.slice(-3)}`;
};

const redactSensitiveText = (value: string): string => {
  let masked = value;
  masked = masked.replace(/\b(sk-[A-Za-z0-9._-]{8,})\b/g, (m) => maskSecret(m));
  masked = masked.replace(/(authorization\s*[:=]\s*bearer\s+)([A-Za-z0-9._-]{6,})/gi, (_m, p1: string, p2: string) => `${p1}${maskSecret(p2)}`);
  masked = masked.replace(/(api[_-]?key\s*[:=]\s*)([A-Za-z0-9._-]{6,})/gi, (_m, p1: string, p2: string) => `${p1}${maskSecret(p2)}`);
  masked = masked.replace(/(token\s*[:=]\s*)([A-Za-z0-9._-]{6,})/gi, (_m, p1: string, p2: string) => `${p1}${maskSecret(p2)}`);
  return masked;
};

const sanitizeForExport = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeForExport(item));
  }
  if (value && typeof value === 'object') {
    const payload = value as Record<string, unknown>;
    const next: Record<string, unknown> = {};
    for (const [key, inner] of Object.entries(payload)) {
      const lowerKey = key.toLowerCase();
      if (EXPORT_SENSITIVE_KEY_FRAGMENTS.some((fragment) => lowerKey.includes(fragment))) {
        next[key] = maskSecret(String(inner ?? ''));
      } else {
        next[key] = sanitizeForExport(inner);
      }
    }
    return next;
  }
  if (typeof value === 'string') {
    return redactSensitiveText(value);
  }
  return value;
};

/**
 * Export filtered events as a sanitized JSON file download.
 * All sensitive fields are redacted before writing.
 */
export const exportEvents = (filteredEvents: readonly RawSSEEvent[]): void => {
  const exportData = filteredEvents.map((event) => ({
    timestamp: event.timestamp,
    type: event.eventType,
    data: sanitizeForExport(event.parsedData),
    size: event.size,
  }));

  const firstPass = JSON.stringify(exportData, null, 2);
  const secondPass = redactSensitiveText(firstPass);

  const blob = new Blob([secondPass], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `finsight-console-${new Date().toISOString().slice(0, 19)}.json`;
  a.click();
  URL.revokeObjectURL(url);
};

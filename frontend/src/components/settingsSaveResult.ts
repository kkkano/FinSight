export function requireSuccessfulConfigSave(response: unknown): void {
  if (!response || typeof response !== 'object') return;
  const result = response as { success?: unknown; error?: unknown; detail?: unknown };
  if (result.success !== false) return;
  const message = typeof result.error === 'string' && result.error.trim()
    ? result.error
    : typeof result.detail === 'string' && result.detail.trim()
      ? result.detail
      : '配置保存失败';
  throw new Error(message);
}

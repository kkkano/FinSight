export function buildMorningBriefDeepDivePrompt(text: string, ticker?: string | null): string {
  const point = text.trim().replace(/[。.!！?？；;\s]+$/u, '');
  const normalizedTicker = String(ticker || '').trim().toUpperCase();
  return normalizedTicker
    ? `晨报提到：${point}。展开讲讲对 ${normalizedTicker} 的影响。`
    : `晨报提到：${point}。展开讲讲它的影响和应对。`;
}

export function buildMorningBriefDeepDiveHref(text: string, ticker?: string | null): string {
  return `/chat?prompt=${encodeURIComponent(buildMorningBriefDeepDivePrompt(text, ticker))}`;
}

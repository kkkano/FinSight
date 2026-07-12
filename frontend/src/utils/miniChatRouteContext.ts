export function getMiniChatRouteSymbol(
  pathname: string,
  fallbackSymbol?: string | null,
): string | null {
  const match = pathname.match(/^\/dashboard(?:\/([^/?#]+))?\/?$/i);
  if (!match) return null;

  const routeSymbol = match[1] ? decodeURIComponent(match[1]) : '';
  const normalized = (routeSymbol || fallbackSymbol || '').trim().toUpperCase();
  return normalized || null;
}

export function routeSupportsMiniChat(pathname: string): boolean {
  return /^\/(?:dashboard|workbench)(?:\/|$)/i.test(pathname);
}

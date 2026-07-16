export function getDashboardRouteSymbol(
  pathname: string,
  fallbackSymbol?: string | null,
): string | null {
  const match = pathname.match(/^\/dashboard(?:\/([^/?#]+))?\/?$/i);
  if (!match) return null;

  const routeSymbol = match[1] ? decodeURIComponent(match[1]) : '';
  const normalized = (routeSymbol || fallbackSymbol || '').trim().toUpperCase();
  return normalized || null;
}

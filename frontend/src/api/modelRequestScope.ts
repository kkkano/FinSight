export function usesModelSelection(url: string): boolean {
  const path = new URL(url, 'https://finsight.invalid').pathname.replace(/\/+$/, '');
  return path === '/api/execute' || path === '/api/execute/resume';
}

/** Canvas 图表读取现有 CSS token，不维护第二套颜色。 */
export function chartTokens() {
  const style = typeof document === 'undefined' ? null : getComputedStyle(document.documentElement);
  const get = (key: string) => style?.getPropertyValue(key).trim() || '';
  const accent = get('--t-accent');
  return { accent: `rgb(${accent || '0 0 0'})`, text: get('--t-text-3'), line: get('--t-line'), border: get('--t-line-2'), surface: get('--t-surface'), up: get('--t-up'), down: get('--t-down'), amber: get('--t-amber'), accentSoft: get('--t-accent-soft') };
}

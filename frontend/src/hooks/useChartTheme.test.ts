import { describe, expect, it } from 'vitest';

import { buildTerminalChartTheme } from './useChartTheme';

describe('buildTerminalChartTheme', () => {
  it('builds the TERMINAL dark chart contract from token fallbacks', () => {
    const theme = buildTerminalChartTheme(true);

    expect(theme.textStyle).toEqual({
      fontFamily: "'JetBrains Mono Variable', Menlo, monospace",
      fontSize: 10.5,
    });
    expect(theme.gridConfig).toEqual({ top: 28, right: 12, bottom: 24, left: 48 });
    expect(theme.primary).toBe('#ff8a00');
    expect(theme.axisLine.lineStyle.color).toBe(theme.border);
    expect(theme.splitLine.lineStyle.color).toBe(theme.grid);
    expect(theme.tooltip.axisPointer.lineStyle).toEqual({ color: theme.muted, type: 'dashed' });
    expect(theme.candle).toEqual({ up: theme.success, down: theme.danger, border: 'transparent' });
    expect(theme.colorPalette).toHaveLength(8);
  });

  it('keeps the light accent on the TERMINAL orange token', () => {
    expect(buildTerminalChartTheme(false).primary).toBe('#e07a18');
  });
});

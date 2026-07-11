import { useMemo } from 'react';
import { useStore } from '../store/useStore';

type ChartLineStyle = { color: string; type?: 'solid' | 'dashed' };

export type ChartTheme = {
  isDark: boolean;
  text: string;
  textSecondary: string;
  muted: string;
  border: string;
  /** 兼容既有 option：网格线颜色。 */
  grid: string;
  tooltipBackground: string;
  tooltipBorder: string;
  tooltipText: string;
  tooltipMuted: string;
  crosshair: string;
  primary: string;
  primarySoft: string;
  primaryFaint: string;
  success: string;
  danger: string;
  warning: string;
  sliderFiller: string;
  splitAreaA: string;
  splitAreaB: string;
  textStyle: { fontFamily: string; fontSize: number };
  gridConfig: { top: number; right: number; bottom: number; left: number };
  axisLine: { lineStyle: ChartLineStyle };
  splitLine: { lineStyle: ChartLineStyle };
  axisLabel: { color: string; fontSize: number };
  tooltip: {
    backgroundColor: string;
    borderColor: string;
    textStyle: { color: string; fontSize: number };
    axisPointer: { type: 'cross'; lineStyle: ChartLineStyle };
  };
  colorPalette: string[];
  candle: { up: string; down: string; border: 'transparent' };
};

const FALLBACKS = {
  light: {
    text: '#17191d', text2: '#565e6a', text3: '#8a93a1', border: '#e2e5ea',
    elevated: '#f8f9fb', grid: '#e8eaef', accent: '224 122 24', up: '#0f9960',
    down: '#d13d3d', warning: '#b97509', surface: '#ffffff',
  },
  dark: {
    text: '#e8eaed', text2: '#9aa3b2', text3: '#5b6472', border: '#232b3a',
    elevated: '#171c27', grid: '#1a2130', accent: '255 138 0', up: '#2fbf7f',
    down: '#ff5d5d', warning: '#f5a623', surface: '#10131a',
  },
} as const;

const readCssVar = (name: string, fallback: string) => {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
};

const rgbTripletToHex = (raw: string, fallback: string) => {
  const parts = raw.split(/\s+/).map(Number).filter(Number.isFinite);
  if (parts.length < 3) return fallback;
  return `#${parts.slice(0, 3).map((part) => Math.max(0, Math.min(255, Math.round(part))).toString(16).padStart(2, '0')).join('')}`;
};

const rgbTripletToRgba = (raw: string, alpha: number, fallback: string) => {
  const parts = raw.split(/\s+/).map(Number).filter(Number.isFinite);
  if (parts.length < 3) return fallback;
  return `rgba(${parts.slice(0, 3).join(', ')}, ${alpha})`;
};

export function buildTerminalChartTheme(isDark: boolean): ChartTheme {
  const fallback = isDark ? FALLBACKS.dark : FALLBACKS.light;
  const text = readCssVar('--t-text', fallback.text);
  const textSecondary = readCssVar('--t-text-2', fallback.text2);
  const muted = readCssVar('--t-text-3', fallback.text3);
  const border = readCssVar('--t-border', fallback.border);
  const grid = readCssVar('--t-chart-grid', fallback.grid);
  const tooltipBackground = readCssVar('--t-elevated', fallback.elevated);
  const accentTriplet = readCssVar('--t-accent', fallback.accent);
  const primary = rgbTripletToHex(accentTriplet, isDark ? '#ff8a00' : '#e07a18');
  const success = readCssVar('--t-up', fallback.up);
  const danger = readCssVar('--t-down', fallback.down);
  const warning = readCssVar('--t-warning', fallback.warning);

  return {
    isDark,
    text,
    textSecondary,
    muted,
    border,
    grid,
    tooltipBackground,
    tooltipBorder: border,
    tooltipText: text,
    tooltipMuted: textSecondary,
    crosshair: muted,
    primary,
    primarySoft: rgbTripletToRgba(accentTriplet, 0.28, 'rgba(255, 138, 0, 0.28)'),
    primaryFaint: rgbTripletToRgba(accentTriplet, 0.08, 'rgba(255, 138, 0, 0.08)'),
    success,
    danger,
    warning,
    sliderFiller: rgbTripletToRgba(accentTriplet, 0.18, 'rgba(255, 138, 0, 0.18)'),
    splitAreaA: readCssVar('--t-surface', fallback.surface),
    splitAreaB: tooltipBackground,
    textStyle: { fontFamily: "'JetBrains Mono Variable', Menlo, monospace", fontSize: 10.5 },
    gridConfig: { top: 28, right: 12, bottom: 24, left: 48 },
    axisLine: { lineStyle: { color: border } },
    splitLine: { lineStyle: { color: grid, type: 'solid' } },
    axisLabel: { color: muted, fontSize: 10 },
    tooltip: {
      backgroundColor: tooltipBackground,
      borderColor: border,
      textStyle: { color: text, fontSize: 11 },
      axisPointer: { type: 'cross', lineStyle: { color: muted, type: 'dashed' } },
    },
    colorPalette: ['#FF8A00', '#6B9EFF', '#2FBF7F', '#9775FA', '#F5A623', '#FF5D5D', '#4DD4E8', '#C0CA33'],
    candle: { up: success, down: danger, border: 'transparent' },
  };
}

export const useChartTheme = (): ChartTheme => {
  const theme = useStore((state) => state.theme);
  const colorConvention = useStore((state) => state.colorConvention);
  return useMemo(() => {
    // 配色习惯切换后重新读取 documentElement 上的 --t-up/--t-down。
    void colorConvention;
    return buildTerminalChartTheme(theme === 'dark');
  }, [colorConvention, theme]);
};

import { useMemo } from 'react';
import { useStore } from '../store/useStore';

export type ChartTheme = {
  isDark: boolean;
  text: string;
  textSecondary: string;
  muted: string;
  border: string;
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
};

const readCssVar = (name: string, fallback: string) => {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
};

const rgbVarToHex = (raw: string, fallback: string) => {
  const parts = raw
    .split(/\s+/)
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v));
  if (parts.length < 3) return fallback;
  return `#${parts
    .slice(0, 3)
    .map((part) => Math.max(0, Math.min(255, Math.round(part))).toString(16).padStart(2, '0'))
    .join('')}`;
};

export const useChartTheme = (): ChartTheme => {
  const theme = useStore((state) => state.theme);

  return useMemo(() => {
    const isDark = theme === 'dark';
    const primary = rgbVarToHex(readCssVar('--fin-primary', isDark ? '59 130 246' : '37 99 235'), isDark ? '#3b82f6' : '#2563eb');

    const success = readCssVar('--fin-success', isDark ? '#0cad92' : '#10b981');
    const danger = readCssVar('--fin-danger', isDark ? '#f74f5c' : '#ef4444');
    const warning = readCssVar('--fin-warning', isDark ? '#f5a623' : '#f59e0b');

    return {
      isDark,
      text: readCssVar('--fin-text', isDark ? '#f8fafc' : '#1e293b'),
      textSecondary: readCssVar('--fin-text-secondary', isDark ? '#cbd5e1' : '#64748b'),
      muted: readCssVar('--fin-muted', isDark ? '#64748b' : '#94a3b8'),
      border: readCssVar('--fin-border', isDark ? '#2a2d38' : '#e2e8f0'),
      grid: isDark ? '#2a2d38' : '#e2e8f0',
      tooltipBackground: isDark ? 'rgba(30, 32, 40, 0.96)' : 'rgba(255, 255, 255, 0.96)',
      tooltipBorder: isDark ? '#3b4152' : '#dbe3ee',
      tooltipText: readCssVar('--fin-text', isDark ? '#f8fafc' : '#1e293b'),
      tooltipMuted: readCssVar('--fin-text-secondary', isDark ? '#cbd5e1' : '#64748b'),
      crosshair: primary,
      primary,
      primarySoft: isDark ? 'rgba(59, 130, 246, 0.28)' : 'rgba(37, 99, 235, 0.22)',
      primaryFaint: isDark ? 'rgba(59, 130, 246, 0.08)' : 'rgba(37, 99, 235, 0.06)',
      success,
      danger,
      warning,
      sliderFiller: isDark ? 'rgba(59, 130, 246, 0.18)' : 'rgba(37, 99, 235, 0.12)',
      splitAreaA: isDark ? 'rgba(255, 255, 255, 0.02)' : 'rgba(248, 250, 252, 0.8)',
      splitAreaB: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(241, 245, 249, 0.7)',
    };
  }, [theme]);
};


import type { StateCreator } from 'zustand';
import type { AppState } from './stateTypes';
import type { Theme, ColorConvention, LayoutMode, ChatStyle } from './stateTypes';
import { writeResearchPreferences } from './researchPreferences';

export const getInitialLayout = (): LayoutMode => {
  if (typeof window === 'undefined') return 'centered';
  const stored = window.localStorage.getItem('finsight-layout');
  return stored === 'full' || stored === 'centered' ? (stored as LayoutMode) : 'centered';
};

export const getInitialChatStyle = (): ChatStyle => {
  if (typeof window === 'undefined') return 'bubble';
  const stored = window.localStorage.getItem('finsight-chat-style');
  return stored === 'flat' ? 'flat' : 'bubble';
};

export const getInitialTheme = (): Theme => {
  if (typeof window === 'undefined') return 'dark';
  const stored = window.localStorage.getItem('finsight-theme');
  if (stored === 'light' || stored === 'dark') return stored;
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  return prefersDark ? 'dark' : 'light';
};

export const getInitialColorConvention = (): ColorConvention => {
  if (typeof window === 'undefined') return 'intl';
  return window.localStorage.getItem('finsight-color-convention') === 'cn' ? 'cn' : 'intl';
};

export const applyThemeClass = (theme: Theme) => {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('light', theme === 'light');
  root.classList.toggle('dark', theme === 'dark');
};

export const applyColorConventionClass = (colorConvention: ColorConvention) => {
  if (typeof document === 'undefined') return;
  document.documentElement.classList.toggle('cn-colors', colorConvention === 'cn');
};

export type ThemeSlice = Pick<AppState, "theme" | "colorConvention" | "layoutMode" | "watchlistAutoConfirm" | "showProviderReasoning" | "chatStyle" | "showRightPanel" | "setTheme" | "setColorConvention" | "setLayoutMode" | "setChatStyle" | "setWatchlistAutoConfirm" | "setShowProviderReasoning" | "setShowRightPanel" | "toggleRightPanel">;

export const createThemeSlice = (initial: { initialTheme: Theme; initialColorConvention: ColorConvention; initialLayout: LayoutMode }): StateCreator<AppState, [], [], ThemeSlice> => (set) => {
 const { initialTheme, initialColorConvention, initialLayout } = initial;
 return {
theme: initialTheme,

colorConvention: initialColorConvention,

layoutMode: initialLayout,

watchlistAutoConfirm: false,

showProviderReasoning: false,

chatStyle: getInitialChatStyle(),

// 右侧市场与执行面板默认收起，按需展开。
  showRightPanel: false,

setTheme: (theme) => {
    set({ theme });
    applyThemeClass(theme);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('finsight-theme', theme);
    }
  },

setColorConvention: (colorConvention) => {
    set({ colorConvention });
    applyColorConventionClass(colorConvention);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('finsight-color-convention', colorConvention);
    }
  },

setLayoutMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-layout', mode);
      }
      return { layoutMode: mode };
    }),

setChatStyle: (style) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-chat-style', style);
      }
      return { chatStyle: style };
    }),

setWatchlistAutoConfirm: (enabled) => set((state) => {
    const preferences = { watchlistAutoConfirm: Boolean(state.authIdentity?.userId) && enabled === true,
      showProviderReasoning: state.showProviderReasoning };
    writeResearchPreferences(state.authIdentity?.userId, preferences);
    return preferences;
  }),

setShowProviderReasoning: (enabled) => set((state) => {
    const preferences = { watchlistAutoConfirm: state.watchlistAutoConfirm,
      showProviderReasoning: Boolean(state.authIdentity?.userId) && enabled === true };
    writeResearchPreferences(state.authIdentity?.userId, preferences);
    return preferences;
  }),

setShowRightPanel: (show) =>
    set({ showRightPanel: show }),

toggleRightPanel: () =>
    set((state) => ({ showRightPanel: !state.showRightPanel }))
 };
};

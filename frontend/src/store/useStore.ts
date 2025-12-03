import { create } from 'zustand';
import type { Message } from '../types';

type Theme = 'dark' | 'light';
type LayoutMode = 'centered' | 'full';

const getInitialLayout = (): LayoutMode => {
  if (typeof window === 'undefined') return 'centered';
  const stored = window.localStorage.getItem('finsight-layout');
  return stored === 'full' || stored === 'centered' ? (stored as LayoutMode) : 'centered';
};

const getInitialTheme = (): Theme => {
  if (typeof window === 'undefined') return 'dark';
  const stored = window.localStorage.getItem('finsight-theme');
  if (stored === 'light' || stored === 'dark') return stored;
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  return prefersDark ? 'dark' : 'light';
};

const applyThemeClass = (theme: Theme) => {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('light', theme === 'light');
  root.classList.toggle('dark', theme === 'dark');
};

const initialTheme = getInitialTheme();
const initialLayout = getInitialLayout();
applyThemeClass(initialTheme);

interface AppState {
  messages: Message[];
  addMessage: (message: Message) => void;
  updateLastMessage: (content: string) => void;
  setLoading: (loading: boolean) => void;
  isChatLoading: boolean;
  abortController: AbortController | null;
  setAbortController: (controller: AbortController | null) => void;
  currentTicker: string | null;
  setTicker: (ticker: string | null) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  layoutMode: LayoutMode;
  setLayoutMode: (mode: LayoutMode) => void;
}

export const useStore = create<AppState>((set) => ({
  messages: [
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '您好，我是 FinSight AI 金融助手。直接输入股票代码或问题（例如：AAPL 股价走势、特斯拉最新新闻），我会用实时数据和图表帮你分析。',
      timestamp: Date.now(),
    },
  ],
  isChatLoading: false,
  currentTicker: null,
  abortController: null,
  theme: initialTheme,
  layoutMode: initialLayout,

  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),

  updateLastMessage: (content) =>
    set((state) => {
      const newMessages = [...state.messages];
      if (newMessages.length > 0) {
        newMessages[newMessages.length - 1].content = content;
      }
      return { messages: newMessages };
    }),

  setLoading: (loading) => set({ isChatLoading: loading }),
  setTicker: (ticker) => set({ currentTicker: ticker }),
  setAbortController: (controller) => set({ abortController: controller }),

  setTheme: (theme) => {
    set({ theme });
    applyThemeClass(theme);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('finsight-theme', theme);
    }
  },

  setLayoutMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-layout', mode);
      }
      return { layoutMode: mode };
    }),
}));

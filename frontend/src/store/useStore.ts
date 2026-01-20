import { create } from 'zustand';
import type { Message } from '../types';

type Theme = 'dark' | 'light';
type LayoutMode = 'centered' | 'full';
type ChatMode = 'smart' | 'traditional';
type PortfolioPositions = Record<string, number>;

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

const getInitialSubscriptionEmail = (): string => {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem('finsight-subscription-email') || '';
};

const getInitialChatMode = (): ChatMode => {
  if (typeof window === 'undefined') return 'smart';
  const stored = window.localStorage.getItem('finsight-chat-mode');
  return stored === 'smart' || stored === 'traditional' ? (stored as ChatMode) : 'smart';
};

const getInitialPortfolioPositions = (): PortfolioPositions => {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem('finsight-portfolio-positions');
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    return Object.entries(parsed).reduce<PortfolioPositions>((acc, [ticker, shares]) => {
      const normalized = ticker.trim().toUpperCase();
      const value = Number(shares);
      if (normalized && Number.isFinite(value) && value > 0) {
        acc[normalized] = value;
      }
      return acc;
    }, {});
  } catch (error) {
    return {};
  }
};

const persistPortfolioPositions = (positions: PortfolioPositions) => {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem('finsight-portfolio-positions', JSON.stringify(positions));
};

const applyThemeClass = (theme: Theme) => {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.classList.toggle('light', theme === 'light');
  root.classList.toggle('dark', theme === 'dark');
};

const initialTheme = getInitialTheme();
const initialLayout = getInitialLayout();
const initialSubscriptionEmail = getInitialSubscriptionEmail();
const initialChatMode = getInitialChatMode();
const initialPortfolioPositions = getInitialPortfolioPositions();
applyThemeClass(initialTheme);

interface AppState {
  messages: Message[];
  addMessage: (message: Message) => void;
  updateMessage: (id: string, patch: Partial<Message>) => void;
  updateLastMessage: (content: string) => void;
  removeMessage: (id: string) => void;
  setLoading: (loading: boolean) => void;
  isChatLoading: boolean;
  statusMessage: string | null;
  statusSince: number | null;
  setStatus: (message: string | null) => void;
  abortController: AbortController | null;
  setAbortController: (controller: AbortController | null) => void;
  currentTicker: string | null;
  setTicker: (ticker: string | null) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  layoutMode: LayoutMode;
  setLayoutMode: (mode: LayoutMode) => void;
  setDraft: (text: string) => void;
  draft: string;
  subscriptionEmail: string;
  setSubscriptionEmail: (email: string) => void;
  chatMode: ChatMode;
  setChatMode: (mode: ChatMode) => void;
  portfolioPositions: PortfolioPositions;
  setPortfolioPosition: (ticker: string, shares: number) => void;
  removePortfolioPosition: (ticker: string) => void;
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
  statusMessage: null,
  statusSince: null,
  currentTicker: null,
  abortController: null,
  draft: '',
  theme: initialTheme,
  layoutMode: initialLayout,
  subscriptionEmail: initialSubscriptionEmail,
  chatMode: initialChatMode,
  portfolioPositions: initialPortfolioPositions,

  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),

  updateMessage: (id, patch) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),

  updateLastMessage: (content) =>
    set((state) => {
      const newMessages = [...state.messages];
      if (newMessages.length > 0) {
        newMessages[newMessages.length - 1].content = content;
      }
      return { messages: newMessages };
    }),

  removeMessage: (id) =>
    set((state) => ({
      messages: state.messages.filter((m) => m.id !== id),
    })),

  setLoading: (loading) => set({ isChatLoading: loading }),
  setStatus: (message) =>
    set(() => ({
      statusMessage: message,
      statusSince: message ? Date.now() : null,
    })),
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

  setSubscriptionEmail: (email) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-subscription-email', email);
      }
      return { subscriptionEmail: email };
    }),

  setChatMode: (mode) =>
    set(() => {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('finsight-chat-mode', mode);
      }
      return { chatMode: mode };
    }),

  setPortfolioPosition: (ticker, shares) =>
    set((state) => {
      const key = ticker.trim().toUpperCase();
      if (!key) return {};
      const next = { ...state.portfolioPositions };
      if (!Number.isFinite(shares) || shares <= 0) {
        delete next[key];
      } else {
        next[key] = shares;
      }
      persistPortfolioPositions(next);
      return { portfolioPositions: next };
    }),

  removePortfolioPosition: (ticker) =>
    set((state) => {
      const key = ticker.trim().toUpperCase();
      if (!key) return {};
      if (!state.portfolioPositions[key]) return {};
      const next = { ...state.portfolioPositions };
      delete next[key];
      persistPortfolioPositions(next);
      return { portfolioPositions: next };
    }),

  setDraft: (text) =>
    set(() => ({ draft: text })),
}));

/**
 * Dashboard Zustand Store
 *
 * 管理 Dashboard 的所有状态，包括资产选择、能力集、自选列表、
 * 布局偏好、新闻模式和聚合数据。支持 localStorage 持久化。
 */
import { create } from 'zustand';
import type {
  ActiveAsset,
  Capabilities,
  WatchItem,
  LayoutPrefs,
  NewsModeType,
  DashboardData,
  SelectionItem,
} from '../types/dashboard';
import { STORAGE_KEYS } from '../types/dashboard';

// === Store 接口 ===
interface DashboardStore {
  // 状态
  activeAsset: ActiveAsset | null;
  capabilities: Capabilities | null;
  watchlist: WatchItem[];
  layoutPrefs: LayoutPrefs;
  newsMode: NewsModeType;
  dashboardData: DashboardData | null;
  isLoading: boolean;
  error: string | null;
  activeSelection: SelectionItem | null;  // 单选兼容：用于旧 UI（MiniChat pill）
  activeSelections: SelectionItem[];      // 多选：用于 Dashboard 新闻多选引用

  // Actions
  setActiveAsset: (asset: ActiveAsset) => void;
  setCapabilities: (caps: Capabilities) => void;
  setWatchlist: (list: WatchItem[]) => void;
  addWatchItem: (item: WatchItem) => void;
  removeWatchItem: (symbol: string) => void;
  setLayoutPrefs: (prefs: LayoutPrefs) => void;
  toggleWidgetVisibility: (widgetId: string) => void;
  resetLayoutPrefs: () => void;
  setNewsMode: (mode: NewsModeType) => void;
  setDashboardData: (data: DashboardData) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setActiveSelection: (selection: SelectionItem | null) => void;
  toggleSelection: (selection: SelectionItem) => void;
  setSelections: (selections: SelectionItem[]) => void;
  clearSelection: () => void;
}

// === 持久化辅助函数 ===
const loadFromStorage = <T>(key: string, fallback: T): T => {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
};

const saveToStorage = (key: string, value: unknown): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // localStorage quota exceeded or other error - silently ignore
  }
};

// === 默认值 ===
const DEFAULT_LAYOUT_PREFS: LayoutPrefs = {
  hidden_widgets: [],
  order: [],
};

// === Store 实例 ===
export const useDashboardStore = create<DashboardStore>((set) => ({
  // 初始状态（从 localStorage 恢复）
  activeAsset: loadFromStorage(STORAGE_KEYS.ACTIVE_ASSET, null),
  capabilities: null,
  watchlist: loadFromStorage(STORAGE_KEYS.WATCHLIST, []),
  layoutPrefs: loadFromStorage(STORAGE_KEYS.LAYOUT, DEFAULT_LAYOUT_PREFS),
  newsMode: loadFromStorage<NewsModeType>(STORAGE_KEYS.NEWS_MODE, 'market'),
  dashboardData: null,
  isLoading: false,
  error: null,
  activeSelection: null,  // 当前选中的新闻/报告
  activeSelections: [],

  // 设置当前资产（同时清除 selection，因为切换股票后之前的引用不再有效）
  setActiveAsset: (asset) => {
    saveToStorage(STORAGE_KEYS.ACTIVE_ASSET, asset);
    set({ activeAsset: asset, error: null, activeSelection: null, activeSelections: [] });
  },

  // 设置能力集
  setCapabilities: (caps) => set({ capabilities: caps }),

  // 设置完整自选列表
  setWatchlist: (list) => {
    saveToStorage(STORAGE_KEYS.WATCHLIST, list);
    set({ watchlist: list });
  },

  // 添加自选项（去重）
  addWatchItem: (item) =>
    set((state) => {
      const exists = state.watchlist.some(
        (w) => w.symbol.toUpperCase() === item.symbol.toUpperCase()
      );
      if (exists) return {};
      const next = [...state.watchlist, item];
      saveToStorage(STORAGE_KEYS.WATCHLIST, next);
      return { watchlist: next };
    }),

  // 删除自选项
  removeWatchItem: (symbol) =>
    set((state) => {
      const next = state.watchlist.filter(
        (w) => w.symbol.toUpperCase() !== symbol.toUpperCase()
      );
      saveToStorage(STORAGE_KEYS.WATCHLIST, next);
      return { watchlist: next };
    }),

  // 设置布局偏好
  setLayoutPrefs: (prefs) => {
    saveToStorage(STORAGE_KEYS.LAYOUT, prefs);
    set({ layoutPrefs: prefs });
  },

  // 切换组件可见性
  toggleWidgetVisibility: (widgetId) =>
    set((state) => {
      const hidden = state.layoutPrefs.hidden_widgets;
      const nextPrefs = hidden.includes(widgetId)
        ? {
            ...state.layoutPrefs,
            hidden_widgets: hidden.filter((id) => id !== widgetId),
          }
        : {
            ...state.layoutPrefs,
            hidden_widgets: [...hidden, widgetId],
          };
      saveToStorage(STORAGE_KEYS.LAYOUT, nextPrefs);
      return { layoutPrefs: nextPrefs };
    }),

  // 重置布局偏好
  resetLayoutPrefs: () => {
    saveToStorage(STORAGE_KEYS.LAYOUT, DEFAULT_LAYOUT_PREFS);
    set({ layoutPrefs: DEFAULT_LAYOUT_PREFS });
  },

  // 设置新闻模式
  setNewsMode: (mode) => {
    saveToStorage(STORAGE_KEYS.NEWS_MODE, mode);
    set({ newsMode: mode });
  },

  // 设置聚合数据
  setDashboardData: (data) => set({ dashboardData: data }),

  // 设置加载状态
  setLoading: (loading) => set({ isLoading: loading }),

  // 设置错误
  setError: (error) => set({ error }),

  // 设置当前选中的新闻/报告（用于 MiniChat 上下文引用）
  setActiveSelection: (selection) =>
    set({
      activeSelection: selection,
      activeSelections: selection ? [selection] : [],
    }),

  // 多选：切换某个 selection 是否被选中
  toggleSelection: (selection) =>
    set((state) => {
      const existing = state.activeSelections;
      const sameType = existing.length === 0 || existing.every((s) => s.type === selection.type);
      const nextBase = sameType ? existing : [];

      const isSelected = nextBase.some((s) => s.id === selection.id);
      const next = isSelected
        ? nextBase.filter((s) => s.id !== selection.id)
        : [...nextBase, selection];

      return {
        activeSelections: next,
        activeSelection: next.length === 1 ? next[0] : null,
      };
    }),

  // 直接设置多选列表（会同步单选兼容字段）
  setSelections: (selections) =>
    set({
      activeSelections: selections,
      activeSelection: selections.length === 1 ? selections[0] : null,
    }),

  // 清除当前选择
  clearSelection: () => set({ activeSelection: null, activeSelections: [] }),
}));

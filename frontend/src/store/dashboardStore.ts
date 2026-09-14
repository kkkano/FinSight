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
  NewsSubTab,
  NewsTagGroup,
  NewsTimeRange,
  DashboardData,
  SelectionItem,
} from '../types/dashboard';
import { STORAGE_KEYS } from '../types/dashboard';
import { apiClient } from '../api/client';
import { useStore } from './useStore';

// === Store 接口 ===
interface DashboardStore {
  // 状态
  activeAsset: ActiveAsset | null;
  capabilities: Capabilities | null;
  watchlist: WatchItem[];
  layoutPrefs: LayoutPrefs;
  newsMode: NewsModeType;
  newsSubTab: NewsSubTab;           // Phase H: 个股/市场7x24/重大事件
  newsTagFilter: NewsTagGroup;      // Phase H: 主题筛选
  newsTimeRange: NewsTimeRange;     // Phase H: 时间范围
  dashboardData: DashboardData | null;
  isLoading: boolean;
  error: string | null;
  activeSelections: SelectionItem[];      // 多选：用于 Dashboard 新闻引用

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
  setNewsSubTab: (tab: NewsSubTab) => void;
  setNewsTagFilter: (tag: NewsTagGroup) => void;
  setNewsTimeRange: (range: NewsTimeRange) => void;
  setDashboardData: (data: DashboardData) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  toggleSelection: (selection: SelectionItem) => void;
  setSelections: (selections: SelectionItem[]) => void;
  clearSelection: () => void;

  // Watchlist API methods (API-first, replace localStorage persistence)
  initWatchlist: () => Promise<void>;
  addWatchItemApi: (ticker: string) => Promise<void>;
  removeWatchItemApi: (ticker: string) => Promise<void>;
  /** @internal in-flight guard */ _isWatchlistLoading: boolean;
  /** @internal loaded flag */ _isWatchlistLoaded: boolean;
  /** @internal owner id for loaded watchlist */ _watchlistOwnerId: string | null;
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

const normalizeLayoutPrefs = (value: unknown): LayoutPrefs => {
  if (!value || typeof value !== 'object') {
    return DEFAULT_LAYOUT_PREFS;
  }

  const raw = value as Partial<LayoutPrefs>;
  const hiddenWidgets = Array.isArray(raw.hidden_widgets)
    ? raw.hidden_widgets.filter((item): item is string => typeof item === 'string')
    : [];
  const order = Array.isArray(raw.order)
    ? raw.order.filter((item): item is string => typeof item === 'string')
    : [];

  return {
    hidden_widgets: hiddenWidgets,
    order,
  };
};

// === Store 实例 ===
export const useDashboardStore = create<DashboardStore>((set, get) => ({
  // 初始状态（从 localStorage 恢复, watchlist 改为 API 加载）
  activeAsset: loadFromStorage(STORAGE_KEYS.ACTIVE_ASSET, null),
  capabilities: null,
  watchlist: [],
  layoutPrefs: normalizeLayoutPrefs(loadFromStorage(STORAGE_KEYS.LAYOUT, DEFAULT_LAYOUT_PREFS)),
  newsMode: loadFromStorage<NewsModeType>(STORAGE_KEYS.NEWS_MODE, 'market'),
  newsSubTab: loadFromStorage<NewsSubTab>(STORAGE_KEYS.NEWS_SUB_TAB, 'stock'),
  newsTagFilter: loadFromStorage<NewsTagGroup>(STORAGE_KEYS.NEWS_TAG_FILTER, '全部'),
  newsTimeRange: loadFromStorage<NewsTimeRange>(STORAGE_KEYS.NEWS_TIME_RANGE, '7d'),
  dashboardData: null,
  isLoading: false,
  error: null,
  activeSelections: [],
  _isWatchlistLoading: false,
  _isWatchlistLoaded: false,
  _watchlistOwnerId: null,

  // 设置当前资产（同时清除 selection 和 dashboardData，
  // 因为切换股票后之前的数据不再有效，必须等新请求返回才渲染）
  setActiveAsset: (asset) => {
    const prev = get().activeAsset;
    saveToStorage(STORAGE_KEYS.ACTIVE_ASSET, asset);
    // Only clear dashboardData when the symbol actually changes,
    // to avoid unnecessary flicker on same-symbol refreshes.
    const symbolChanged = prev?.symbol !== asset.symbol;
    set({
      activeAsset: asset,
      error: null,
      activeSelections: [],
      ...(symbolChanged ? { dashboardData: null } : {}),
    });
  },

  // 设置能力集
  setCapabilities: (caps) => set({ capabilities: caps }),

  // 设置完整自选列表（本地状态，不持久化到 localStorage）
  setWatchlist: (list) => {
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
      return { watchlist: next };
    }),

  // 删除自选项
  removeWatchItem: (symbol) =>
    set((state) => {
      const next = state.watchlist.filter(
        (w) => w.symbol.toUpperCase() !== symbol.toUpperCase()
      );
      return { watchlist: next };
    }),

  // 设置布局偏好
  setLayoutPrefs: (prefs) => {
    const normalized = normalizeLayoutPrefs(prefs);
    saveToStorage(STORAGE_KEYS.LAYOUT, normalized);
    set({ layoutPrefs: normalized });
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

  // Phase H: 设置新闻子标签 (个股/市场7x24/重大事件)
  setNewsSubTab: (tab) => {
    saveToStorage(STORAGE_KEYS.NEWS_SUB_TAB, tab);
    set({ newsSubTab: tab });
  },

  // Phase H: 设置新闻主题筛选
  setNewsTagFilter: (tag) => {
    saveToStorage(STORAGE_KEYS.NEWS_TAG_FILTER, tag);
    set({ newsTagFilter: tag });
  },

  // Phase H: 设置新闻时间范围
  setNewsTimeRange: (range) => {
    saveToStorage(STORAGE_KEYS.NEWS_TIME_RANGE, range);
    set({ newsTimeRange: range });
  },

  // 设置聚合数据
  setDashboardData: (data) => set({ dashboardData: data }),

  // 设置加载状态
  setLoading: (loading) => set({ isLoading: loading }),

  // 设置错误
  setError: (error) => set({ error }),

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

      return { activeSelections: next };
    }),

  // 直接设置多选列表
  setSelections: (selections) => set({ activeSelections: selections }),

  // 清除当前选择
  clearSelection: () => set({ activeSelections: [] }),

  // --- Watchlist API 方法 (API-first, 替代 localStorage 持久化) ---

  initWatchlist: async () => {
    const ownerId = String(useStore.getState().authIdentity?.userId || '').trim();
    if (!ownerId) {
      set({
        watchlist: [],
        _isWatchlistLoaded: true,
        _isWatchlistLoading: false,
        _watchlistOwnerId: null,
      });
      return;
    }

    const { _isWatchlistLoaded, _isWatchlistLoading, _watchlistOwnerId } = get();
    if (_isWatchlistLoading && _watchlistOwnerId === ownerId) return;
    if (_isWatchlistLoaded && _watchlistOwnerId === ownerId) return;

    set({
      watchlist: [],
      _isWatchlistLoaded: false,
      _isWatchlistLoading: true,
      _watchlistOwnerId: ownerId,
    });

    try {
      const response = await apiClient.getWatchlist();
      if (
        useStore.getState().authIdentity?.userId !== ownerId
        || get()._watchlistOwnerId !== ownerId
      ) return;
      const items = Array.isArray(response?.items) ? response.items : [];
      const watchItems: WatchItem[] = items.map((item) => ({
        symbol: item.ticker.toUpperCase(),
        type: 'equity',
        name: item.note || item.ticker.toUpperCase(),
      }));

      set({
        watchlist: watchItems,
        _isWatchlistLoaded: true,
        _isWatchlistLoading: false,
        _watchlistOwnerId: ownerId,
      });
    } catch {
      if (get()._watchlistOwnerId === ownerId) {
        set({ _isWatchlistLoading: false });
      }
    }
  },

  addWatchItemApi: async (ticker: string) => {
    const response = await apiClient.addWatchlistItem({ ticker });
    const normalized = response.item.ticker;
    get().addWatchItem({
      symbol: normalized,
      type: 'equity',
      name: response.item.note || normalized,
    });
  },

  removeWatchItemApi: async (ticker: string) => {
    await apiClient.removeWatchlistItem(ticker);
    get().removeWatchItem(ticker);
  },
}));

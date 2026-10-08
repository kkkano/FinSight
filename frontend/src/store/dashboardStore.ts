/**
 * Dashboard Zustand Store
 *
 * 只管理资产选择、布局和新闻选区；远程资源由 Query Cache 管理。
 */
import { create } from 'zustand';
import type {
  ActiveAsset,
  LayoutPrefs,
  NewsModeType,
  NewsSubTab,
  NewsTagGroup,
  NewsTimeRange,
  SelectionItem,
} from '../types/dashboard';
import { STORAGE_KEYS } from '../types/dashboard';

// === Store 接口 ===
interface DashboardStore {
  // 状态
  activeAsset: ActiveAsset | null;
  layoutPrefs: LayoutPrefs;
  newsMode: NewsModeType;
  newsSubTab: NewsSubTab;           // Phase H: 个股/市场7x24/重大事件
  newsTagFilter: NewsTagGroup;      // Phase H: 主题筛选
  newsTimeRange: NewsTimeRange;     // Phase H: 时间范围
  activeSelections: SelectionItem[];      // 多选：用于 Dashboard 新闻引用

  // Actions
  setActiveAsset: (asset: ActiveAsset) => void;
  setLayoutPrefs: (prefs: LayoutPrefs) => void;
  toggleWidgetVisibility: (widgetId: string) => void;
  resetLayoutPrefs: () => void;
  setNewsMode: (mode: NewsModeType) => void;
  setNewsSubTab: (tab: NewsSubTab) => void;
  setNewsTagFilter: (tag: NewsTagGroup) => void;
  setNewsTimeRange: (range: NewsTimeRange) => void;
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
export const useDashboardStore = create<DashboardStore>((set) => ({
  // 初始状态（从 localStorage 恢复, watchlist 改为 API 加载）
  activeAsset: loadFromStorage(STORAGE_KEYS.ACTIVE_ASSET, null),
  layoutPrefs: normalizeLayoutPrefs(loadFromStorage(STORAGE_KEYS.LAYOUT, DEFAULT_LAYOUT_PREFS)),
  newsMode: loadFromStorage<NewsModeType>(STORAGE_KEYS.NEWS_MODE, 'market'),
  newsSubTab: loadFromStorage<NewsSubTab>(STORAGE_KEYS.NEWS_SUB_TAB, 'stock'),
  newsTagFilter: loadFromStorage<NewsTagGroup>(STORAGE_KEYS.NEWS_TAG_FILTER, '全部'),
  newsTimeRange: loadFromStorage<NewsTimeRange>(STORAGE_KEYS.NEWS_TIME_RANGE, '7d'),
  activeSelections: [],

  setActiveAsset: (asset) => {
    saveToStorage(STORAGE_KEYS.ACTIVE_ASSET, asset);
    set((state) => ({ activeAsset: asset, activeSelections: state.activeAsset?.symbol === asset.symbol ? state.activeSelections : [] }));
  },

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

}));

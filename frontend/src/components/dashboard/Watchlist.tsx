/**
 * Dashboard Watchlist 组件
 *
 * 功能：
 * - 渲染自选列表（含实时价格）
 * - 点击切换激活资产
 * - 添加/删除自选项
 * - 外链到 Yahoo Finance
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { Plus, ExternalLink, X, RefreshCw } from 'lucide-react';
import { useDashboardStore } from '../../store/dashboardStore';
import { apiClient } from '../../api/client';
import type { WatchItem, ActiveAsset } from '../../types/dashboard';

// 价格数据类型
type QuoteData = {
  price?: number | null;
  change?: number | null;
  changePct?: number | null;
  loading?: boolean;
};

// 解析价格响应
const parsePriceText = (payload: any): QuoteData => {
  if (!payload) return {};
  if (typeof payload === 'object' && payload.price) {
    return {
      price: Number(payload.price),
      change: payload.change !== undefined ? Number(payload.change) : undefined,
      changePct: payload.change_percent !== undefined ? Number(payload.change_percent) : undefined,
    };
  }
  const text = typeof payload === 'string' ? payload : String(payload);
  const priceMatch = text.match(/Current Price:\s*\$([0-9.,]+)/i);
  const changeMatch = text.match(/Change:\s*([+-]?[0-9.]+)/i);
  const pctMatch = text.match(/\(([-+]?[0-9.]+)%\)/);
  const fallbackPrice = text.match(/\$([0-9]+(?:\.[0-9]+)?)/);

  const price = priceMatch ? Number(priceMatch[1].replace(/,/g, '')) : fallbackPrice ? Number(fallbackPrice[1]) : undefined;
  const change = changeMatch ? Number(changeMatch[1]) : undefined;
  const changePct = pctMatch ? Number(pctMatch[1]) : undefined;
  return { price, change, changePct };
};

// 格式化涨跌幅
const formatChangePct = (value?: number | null) => {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

interface WatchlistProps {
  /** 当前激活的 symbol */
  activeSymbol?: string | null;
  /** symbol 选择回调 */
  onSymbolSelect?: (symbol: string) => void;
}

export function Watchlist({ activeSymbol, onSymbolSelect }: WatchlistProps) {
  const { watchlist, addWatchItem, removeWatchItem, setActiveAsset } =
    useDashboardStore();

  // 添加模式状态
  const [isAdding, setIsAdding] = useState(false);
  const [newSymbol, setNewSymbol] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  // 价格数据状态
  const [quotes, setQuotes] = useState<Record<string, QuoteData>>({});
  const [isRefreshing, setIsRefreshing] = useState(false);

  // 右键菜单状态
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    symbol: string;
  } | null>(null);

  // 获取所有 watchlist 项的价格
  const loadQuotes = useCallback(async () => {
    if (watchlist.length === 0) return;

    setIsRefreshing(true);
    const results: Record<string, QuoteData> = {};

    await Promise.all(
      watchlist.map(async (item) => {
        try {
          const response = await apiClient.fetchStockPrice(item.symbol);
          const payload = response?.data ?? response;
          const parsed = parsePriceText(payload?.data ?? payload);
          results[item.symbol] = parsed;
        } catch {
          results[item.symbol] = {};
        }
      })
    );

    setQuotes(results);
    setIsRefreshing(false);
  }, [watchlist]);

  // 初始加载 + 定期刷新（每分钟）
  useEffect(() => {
    loadQuotes();
    const timer = setInterval(loadQuotes, 60000);
    return () => clearInterval(timer);
  }, [loadQuotes]);

  // 聚焦输入框
  useEffect(() => {
    if (isAdding && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isAdding]);

  // 点击外部关闭右键菜单
  useEffect(() => {
    const handleClickOutside = () => setContextMenu(null);
    if (contextMenu) {
      document.addEventListener('click', handleClickOutside);
      return () => document.removeEventListener('click', handleClickOutside);
    }
  }, [contextMenu]);

  // 处理条目点击
  const handleItemClick = (item: WatchItem) => {
    // 构造 ActiveAsset
    const asset: ActiveAsset = {
      symbol: item.symbol,
      type: item.type as ActiveAsset['type'],
      display_name: item.name || item.symbol,
    };
    setActiveAsset(asset);
    onSymbolSelect?.(item.symbol);
  };

  // 处理右键菜单
  const handleContextMenu = (e: React.MouseEvent, symbol: string) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, symbol });
  };

  // 处理删除
  const handleDelete = (symbol: string) => {
    removeWatchItem(symbol);
    setContextMenu(null);
  };

  // 处理添加
  const handleAdd = () => {
    const symbol = newSymbol.trim().toUpperCase();
    if (!symbol) return;

    // 检查是否已存在
    const exists = watchlist.some(
      (w) => w.symbol.toUpperCase() === symbol
    );
    if (exists) {
      setNewSymbol('');
      setIsAdding(false);
      return;
    }

    // 添加到 watchlist
    addWatchItem({
      symbol,
      type: 'equity', // 默认类型，后端会解析正确类型
      name: symbol,
    });

    setNewSymbol('');
    setIsAdding(false);

    // 选中新添加的 symbol
    onSymbolSelect?.(symbol);
  };

  // 处理键盘事件
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleAdd();
    } else if (e.key === 'Escape') {
      setIsAdding(false);
      setNewSymbol('');
    }
  };

  // 打开 Yahoo Finance
  const openYahooFinance = (symbol: string) => {
    window.open(`https://finance.yahoo.com/quote/${symbol}`, '_blank');
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-fin-border">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-fin-text">自选列表</h2>
          <div className="flex items-center gap-1">
            {/* 刷新按钮 */}
            <button
              onClick={loadQuotes}
              disabled={isRefreshing}
              className="p-1.5 rounded-md hover:bg-fin-hover transition-colors text-fin-text-secondary hover:text-fin-primary disabled:opacity-50"
              title="刷新报价"
            >
              <RefreshCw size={12} className={isRefreshing ? 'animate-spin' : ''} />
            </button>
            {/* 添加按钮 */}
            <button
              onClick={() => setIsAdding(true)}
              className="p-1.5 rounded-md hover:bg-fin-hover transition-colors text-fin-text-secondary hover:text-fin-primary"
              title="添加自选"
            >
              <Plus size={14} />
            </button>
          </div>
        </div>

        {/* 添加输入框 */}
        {isAdding && (
          <div className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入代码"
              className="flex-1 px-2 py-1.5 text-xs border border-fin-border rounded bg-fin-bg text-fin-text focus:outline-none focus:border-fin-primary"
            />
            <button
              onClick={handleAdd}
              className="px-2 py-1.5 text-xs bg-fin-primary text-white rounded hover:opacity-90 transition-opacity"
            >
              添加
            </button>
            <button
              onClick={() => {
                setIsAdding(false);
                setNewSymbol('');
              }}
              className="p-1.5 text-fin-muted hover:text-fin-text transition-colors"
            >
              <X size={12} />
            </button>
          </div>
        )}
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto">
        {watchlist.length === 0 ? (
          <div className="p-4 text-center text-xs text-fin-muted">
            暂无自选，点击上方 + 添加
          </div>
        ) : (
          <ul className="py-2">
            {watchlist.map((item) => {
              const isActive =
                activeSymbol?.toUpperCase() === item.symbol.toUpperCase();
              const quote = quotes[item.symbol] || {};
              const hasPrice = typeof quote.price === 'number';
              const isUp = (quote.changePct ?? 0) >= 0;

              return (
                <li
                  key={item.symbol}
                  onClick={() => handleItemClick(item)}
                  onContextMenu={(e) => handleContextMenu(e, item.symbol)}
                  className={`group flex items-center justify-between px-4 py-2.5 cursor-pointer transition-colors ${
                    isActive
                      ? 'bg-fin-primary/10 border-l-2 border-fin-primary'
                      : 'hover:bg-fin-hover border-l-2 border-transparent'
                  }`}
                >
                  {/* 左侧：Symbol 和名称 */}
                  <div className="flex flex-col min-w-0 flex-shrink-0">
                    <span
                      className={`text-sm font-medium truncate ${
                        isActive ? 'text-fin-primary' : 'text-fin-text'
                      }`}
                    >
                      {item.symbol}
                    </span>
                    <span className="text-[10px] text-fin-muted truncate max-w-[80px]">
                      {item.name || item.symbol}
                    </span>
                  </div>

                  {/* 中间：价格和涨跌幅 */}
                  <div className="flex flex-col items-end flex-1 mx-2">
                    <span className="text-xs font-medium text-fin-text">
                      {hasPrice ? `$${quote.price!.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '--'}
                    </span>
                    <span className={`text-[10px] font-medium ${isUp ? 'text-fin-success' : 'text-fin-danger'}`}>
                      {hasPrice ? formatChangePct(quote.changePct) : '--'}
                    </span>
                  </div>

                  {/* 右侧：操作按钮（悬浮显示） */}
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                    {/* 外链按钮 */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        openYahooFinance(item.symbol);
                      }}
                      className="p-1 rounded hover:bg-fin-bg-secondary text-fin-muted hover:text-fin-primary transition-colors"
                      title="在 Yahoo Finance 查看"
                    >
                      <ExternalLink size={12} />
                    </button>

                    {/* 删除按钮 */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(item.symbol);
                      }}
                      className="p-1 rounded hover:bg-fin-bg-secondary text-fin-muted hover:text-fin-danger transition-colors"
                      title="删除"
                    >
                      <X size={12} />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* 右键菜单 */}
      {contextMenu && (
        <div
          className="fixed z-50 bg-fin-card border border-fin-border rounded-lg shadow-lg py-1 min-w-[120px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            onClick={() => openYahooFinance(contextMenu.symbol)}
            className="w-full px-3 py-1.5 text-left text-xs text-fin-text hover:bg-fin-hover flex items-center gap-2"
          >
            <ExternalLink size={12} />
            在 Yahoo 查看
          </button>
          <button
            onClick={() => handleDelete(contextMenu.symbol)}
            className="w-full px-3 py-1.5 text-left text-xs text-fin-danger hover:bg-fin-hover flex items-center gap-2"
          >
            <X size={12} />
            删除
          </button>
        </div>
      )}

      {/* 底部信息 */}
      <div className="p-3 border-t border-fin-border text-center">
        <span className="text-[10px] text-fin-muted">
          共 {watchlist.length} 个自选
        </span>
      </div>
    </div>
  );
}

export default Watchlist;

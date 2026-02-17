/**
 * Dashboard Watchlist 组件
 *
 * 功能：
 * - 渲染自选列表（含实时价格）
 * - 点击切换激活资产
 * - 添加/删除自选项
 * - 内联编辑持仓股数
 * - 外链到 Yahoo Finance
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { Plus, ExternalLink, X, RefreshCw, Package, Check } from 'lucide-react';
import { useDashboardStore } from '../../store/dashboardStore';
import { useStore } from '../../store/useStore';
import { apiClient } from '../../api/client';
import type { WatchItem, ActiveAsset } from '../../types/dashboard';
// 共享 UI 组件
import { Button, Input, useToast } from '../ui';

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
  const { watchlist, addWatchItemApi, removeWatchItemApi, setActiveAsset } =
    useDashboardStore();
  const { portfolioPositions, setPortfolioPosition, removePortfolioPosition } =
    useStore();
  const { toast } = useToast();

  // 添加模式状态
  const [isAdding, setIsAdding] = useState(false);
  const [newSymbol, setNewSymbol] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  // 价格数据状态
  const [quotes, setQuotes] = useState<Record<string, QuoteData>>({});
  const [isRefreshing, setIsRefreshing] = useState(false);

  // 持仓编辑状态：正在编辑哪个 symbol（null 表示不在编辑）
  const [editingSymbol, setEditingSymbol] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState('');
  const holdingsInputRef = useRef<HTMLInputElement>(null);

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

  // 持仓编辑：聚焦输入框
  useEffect(() => {
    if (editingSymbol && holdingsInputRef.current) {
      holdingsInputRef.current.focus();
      holdingsInputRef.current.select();
    }
  }, [editingSymbol]);

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
    // 如果正在编辑持仓，点击条目不切换资产
    if (editingSymbol) return;

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
  const handleDelete = async (symbol: string) => {
    try {
      await removeWatchItemApi(symbol);
    } catch (error) {
      const message = error instanceof Error ? error.message : '移除失败，请稍后重试';
      toast({
        type: 'error',
        title: '移除自选失败',
        message,
      });
    } finally {
      setContextMenu(null);
    }
  };

  // 处理添加
  const handleAdd = async () => {
    const symbol = newSymbol.trim().toUpperCase();
    if (!symbol) return;

    const exists = watchlist.some(
      (w) => w.symbol.toUpperCase() === symbol
    );
    if (exists) {
      setNewSymbol('');
      setIsAdding(false);
      return;
    }

    try {
      await addWatchItemApi(symbol);
      setNewSymbol('');
      setIsAdding(false);
      onSymbolSelect?.(symbol);
    } catch (error) {
      const message = error instanceof Error ? error.message : '添加失败，请稍后重试';
      toast({
        type: 'error',
        title: '添加自选失败',
        message,
      });
    }
  };

  // 处理键盘事件（添加 ticker）
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      void handleAdd();
    } else if (e.key === 'Escape') {
      setIsAdding(false);
      setNewSymbol('');
    }
  };

  // --- 持仓编辑 ---
  const startEditHoldings = (symbol: string) => {
    const key = symbol.toUpperCase();
    const current = portfolioPositions[key] || 0;
    setEditingSymbol(symbol);
    setEditingValue(current > 0 ? String(current) : '');
  };

  const saveHoldings = () => {
    if (!editingSymbol) return;
    const key = editingSymbol.toUpperCase();
    const parsed = Number(editingValue);

    if (!editingValue.trim() || Number.isNaN(parsed) || parsed <= 0) {
      removePortfolioPosition(key);
    } else {
      setPortfolioPosition(key, parsed);
    }

    setEditingSymbol(null);
    setEditingValue('');
  };

  const cancelEditHoldings = () => {
    setEditingSymbol(null);
    setEditingValue('');
  };

  const handleHoldingsKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      saveHoldings();
    } else if (e.key === 'Escape') {
      cancelEditHoldings();
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
            <Button
              variant="ghost"
              size="sm"
              onClick={loadQuotes}
              disabled={isRefreshing}
              aria-label="刷新报价"
              className="p-1.5"
              title="刷新报价"
            >
              <RefreshCw size={12} className={isRefreshing ? 'animate-spin' : ''} />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsAdding(true)}
              aria-label="添加自选"
              className="p-1.5"
              title="添加自选"
            >
              <Plus size={14} />
            </Button>
          </div>
        </div>

        {/* 添加输入框 */}
        {isAdding && (
          <div className="flex gap-2">
            <Input
              ref={inputRef}
              type="text"
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入代码"
              aria-label="输入股票代码"
              className="flex-1 text-xs py-1.5 px-2"
            />
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                void handleAdd();
              }}
              aria-label="确认添加"
            >
              添加
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setIsAdding(false);
                setNewSymbol('');
              }}
              aria-label="取消添加"
              className="p-1.5 text-fin-muted hover:text-fin-text"
            >
              <X size={12} />
            </Button>
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
              const symbolKey = item.symbol.toUpperCase();
              const shares = portfolioPositions[symbolKey] || 0;
              const isEditingThis = editingSymbol === item.symbol;

              return (
                <li
                  key={item.symbol}
                  onClick={() => handleItemClick(item)}
                  onContextMenu={(e) => handleContextMenu(e, item.symbol)}
                  className={`group flex flex-col px-4 py-2.5 cursor-pointer transition-colors ${
                    isActive
                      ? 'bg-fin-primary/10 border-l-2 border-fin-primary'
                      : 'hover:bg-fin-hover border-l-2 border-transparent'
                  }`}
                >
                  {/* 主行：Symbol + 价格 + 操作 */}
                  <div className="flex items-center justify-between">
                    {/* 左侧：Symbol 和名称 */}
                    <div className="flex flex-col min-w-0 flex-shrink-0">
                      <span
                        className={`text-sm font-medium truncate ${
                          isActive ? 'text-fin-primary' : 'text-fin-text'
                        }`}
                      >
                        {item.symbol}
                      </span>
                      <span className="text-2xs text-fin-muted truncate max-w-[80px]">
                        {item.name || item.symbol}
                      </span>
                    </div>

                    {/* 中间：价格和涨跌幅 */}
                    <div className="flex flex-col items-end flex-1 mx-2">
                      <span className="text-xs font-medium text-fin-text">
                        {hasPrice ? `$${quote.price!.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '--'}
                      </span>
                      <span className={`text-2xs font-medium ${isUp ? 'text-fin-success' : 'text-fin-danger'}`}>
                        {hasPrice ? formatChangePct(quote.changePct) : '--'}
                      </span>
                    </div>

                    {/* 右侧：操作按钮（悬浮显示） */}
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                      {/* 持仓编辑按钮 */}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          startEditHoldings(item.symbol);
                        }}
                        aria-label={`设置 ${item.symbol} 持仓`}
                        className="p-1 rounded hover:bg-fin-bg-secondary text-fin-muted hover:text-fin-primary"
                        title="设置持仓"
                      >
                        <Package size={12} />
                      </Button>
                      {/* 外链按钮 */}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          openYahooFinance(item.symbol);
                        }}
                        aria-label={`在 Yahoo Finance 查看 ${item.symbol}`}
                        className="p-1 rounded hover:bg-fin-bg-secondary text-fin-muted hover:text-fin-primary"
                        title="在 Yahoo Finance 查看"
                      >
                        <ExternalLink size={12} />
                      </Button>
                      {/* 删除按钮 */}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDelete(item.symbol);
                        }}
                        aria-label={`从自选列表中删除 ${item.symbol}`}
                        className="p-1 rounded hover:bg-fin-bg-secondary text-fin-muted hover:text-fin-danger"
                        title="删除"
                      >
                        <X size={12} />
                      </Button>
                    </div>
                  </div>

                  {/* 持仓徽章（非编辑态） */}
                  {shares > 0 && !isEditingThis && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        startEditHoldings(item.symbol);
                      }}
                      className="mt-1 text-2xs text-fin-primary bg-fin-primary/10 px-1.5 py-0.5 rounded-full w-fit hover:bg-fin-primary/20 transition-colors"
                    >
                      持仓 {shares} 股
                    </button>
                  )}

                  {/* 持仓内联编辑 */}
                  {isEditingThis && (
                    <div
                      className="flex items-center gap-1.5 mt-1.5"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Package size={10} className="text-fin-muted shrink-0" />
                      <input
                        ref={holdingsInputRef}
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="1"
                        value={editingValue}
                        onChange={(e) => setEditingValue(e.target.value)}
                        onKeyDown={handleHoldingsKeyDown}
                        onBlur={saveHoldings}
                        placeholder="股数（0=清除）"
                        className="flex-1 min-w-0 px-1.5 py-0.5 text-2xs rounded border border-fin-primary/50 bg-fin-bg text-fin-text text-right focus:outline-none focus:border-fin-primary"
                      />
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={saveHoldings}
                        aria-label="确认持仓"
                        className="p-0.5 text-fin-success hover:text-fin-success"
                        title="确认"
                      >
                        <Check size={12} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={cancelEditHoldings}
                        aria-label="取消编辑"
                        className="p-0.5 text-fin-muted hover:text-fin-danger"
                        title="取消"
                      >
                        <X size={12} />
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* 右键菜单 */}
      {contextMenu && (
        <div
          className="fixed z-50 bg-fin-card border border-fin-border rounded-lg shadow-lg py-1 min-w-[140px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              startEditHoldings(contextMenu.symbol);
              setContextMenu(null);
            }}
            className="w-full px-3 py-1.5 text-left text-xs justify-start"
          >
            <Package size={12} />
            设置持仓
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => openYahooFinance(contextMenu.symbol)}
            className="w-full px-3 py-1.5 text-left text-xs justify-start"
          >
            <ExternalLink size={12} />
            在 Yahoo 查看
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              void handleDelete(contextMenu.symbol);
            }}
            className="w-full px-3 py-1.5 text-left text-xs text-fin-danger justify-start"
          >
            <X size={12} />
            删除
          </Button>
        </div>
      )}

      {/* 底部信息 */}
      <div className="p-3 border-t border-fin-border text-center">
        <span className="text-2xs text-fin-muted">
          共 {watchlist.length} 个自选
        </span>
      </div>
    </div>
  );
}

export default Watchlist;

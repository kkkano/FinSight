import { useEffect, useState } from 'react';
import { ChatList } from './components/ChatList';
import Sidebar from './components/Sidebar';
import { ChatInput } from './components/ChatInput';
import { SettingsModal } from './components/SettingsModal';
import { Settings, Sun, Moon } from 'lucide-react';
import { useStore } from './store/useStore';
import { apiClient } from './api/client';
import { RightPanel } from './components/RightPanel';

// 市场指数配置
const MARKET_INDICES = [
  { label: 'S&P 500', ticker: '^GSPC', flag: '🇺🇸' },
  { label: '沪深300', ticker: '000300.SS', flag: '🇨🇳' },
  { label: '黄金', ticker: 'GC=F', flag: '🌕' },
  { label: 'BTC', ticker: 'BTC-USD', flag: '₿' },
];

type MarketQuote = {
  label: string;
  flag: string;
  price?: number;
  changePct?: number;
  loading?: boolean;
};

function App() {
  const [isChartPanelExpanded, setIsChartPanelExpanded] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [userCollapsed, setUserCollapsed] = useState(false);
  const [marketQuotes, setMarketQuotes] = useState<MarketQuote[]>(
    MARKET_INDICES.map(m => ({ label: m.label, flag: m.flag, loading: true }))
  );
  const { currentTicker, messages, theme, setTheme, layoutMode } = useStore();

  // 加载市场指数数据
  const loadMarketQuotes = async () => {
    const results = await Promise.all(
      MARKET_INDICES.map(async (item) => {
        try {
          const response = await apiClient.fetchStockPrice(item.ticker);
          const payload = response?.data ?? response;
          const data = payload?.data ?? payload;
          // 解析价格和涨跌幅
          let price: number | undefined;
          let changePct: number | undefined;
          if (typeof data === 'object' && data.price) {
            price = Number(data.price);
            changePct = data.change_percent !== undefined ? Number(data.change_percent) : undefined;
          } else if (typeof data === 'string') {
            const priceMatch = data.match(/\$([0-9.,]+)/);
            const pctMatch = data.match(/\(([-+]?[0-9.]+)%\)/);
            price = priceMatch ? Number(priceMatch[1].replace(/,/g, '')) : undefined;
            changePct = pctMatch ? Number(pctMatch[1]) : undefined;
          }
          return { label: item.label, flag: item.flag, price, changePct, loading: false };
        } catch {
          return { label: item.label, flag: item.flag, loading: false };
        }
      })
    );
    setMarketQuotes(results);
  };

  // 初始加载 + 定时刷新
  useEffect(() => {
    loadMarketQuotes();
    const timer = setInterval(loadMarketQuotes, 60000);
    return () => clearInterval(timer);
  }, []);

  // 生成图表时自动展开右侧面板（仅当用户未手动收起）
  useEffect(() => {
    if (currentTicker && !isChartPanelExpanded && !userCollapsed) {
      setIsChartPanelExpanded(true);
    }
  }, [currentTicker, isChartPanelExpanded, userCollapsed]);

  // ticker 变化时重置手动折叠标记
  useEffect(() => {
    if (currentTicker) {
      setUserCollapsed(false);
    }
  }, [currentTicker]);

  const formatChangePct = (value?: number) => {
    if (value === undefined || Number.isNaN(value)) return null;
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  return (
    <div className="flex h-screen w-screen bg-fin-bg text-fin-text font-mono overflow-hidden">
      {/* 1. Sidebar (Fixed width) */}
      <Sidebar onSettingsClick={() => setIsSettingsOpen(true)} />

      {/* 2. Main Workspace (Flex fill) */}
      <div className="flex-1 flex flex-col h-full overflow-hidden relative">
        {/* Header */}
        <header className="h-[60px] bg-fin-card border-b border-fin-border flex items-center justify-between px-6 shrink-0">
          <div className="flex gap-6 text-xs text-fin-text font-medium">
            {marketQuotes.map((q) => (
              <span key={q.label} className="flex items-center gap-1">
                {q.flag} {q.label}:{' '}
                {q.loading ? (
                  <span className="text-fin-muted">...</span>
                ) : q.changePct !== undefined ? (
                  <span className={q.changePct >= 0 ? 'text-fin-success' : 'text-fin-danger'}>
                    {formatChangePct(q.changePct)}
                  </span>
                ) : q.price !== undefined ? (
                  <span className="text-fin-warning">${q.price.toLocaleString()}</span>
                ) : (
                  <span className="text-fin-muted">--</span>
                )}
              </span>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-fin-text-secondary"
            >
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button className="px-3 py-1.5 rounded-lg border border-fin-border bg-fin-bg hover:bg-fin-hover transition-colors text-xs font-medium text-fin-text">
              导出 PDF
            </button>
          </div>
        </header>

        {/* Workspace Grid: Chat + Aux Panel */}
        <div className="flex-1 flex overflow-hidden p-5 gap-5">
          {/* Left: Chat Interaction */}
          <div className="flex-1 bg-fin-card border border-fin-border rounded-2xl flex flex-col overflow-hidden shadow-sm">
            <ChatList />
            <ChatInput />
          </div>

          {/* Right: Auxiliary Panel (Visualization & Context) */}
          <div className={`w-[380px] flex flex-col gap-4 transition-all duration-300 ${isChartPanelExpanded ? '' : '-mr-[380px] hidden'}`}>
            <RightPanel onCollapse={() => setIsChartPanelExpanded(!isChartPanelExpanded)} />
          </div>
        </div>
      </div>

      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
    </div>
  );
}

export default App;

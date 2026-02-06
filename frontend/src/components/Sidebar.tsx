import React, { useEffect, useState } from 'react';
import { MessageSquare, LayoutDashboard, FileText, Bell, Settings, Plus, User, X } from 'lucide-react';
import { apiClient } from '../api/client';
import { useStore } from '../store/useStore';

interface WatchlistItem {
  symbol: string;
  name: string;
  price?: string;
  change?: string;
  isUp?: boolean;
}

interface SidebarProps {
  onSettingsClick?: () => void;
  onSubscribeClick?: () => void;
  onDashboardClick?: (symbol: string) => void;
  onChatClick?: () => void;
  currentView?: 'chat' | 'dashboard';
}

const DEFAULT_USER_ID = 'default_user';

const RISK_LABELS: Record<string, string> = {
  conservative: '保守型',
  balanced: '稳健型',
  aggressive: '进取型',
};

const Sidebar: React.FC<SidebarProps> = ({
  onSettingsClick,
  onSubscribeClick,
  onDashboardClick,
  onChatClick,
  currentView,
}) => {
  const [activeTab, setActiveTab] = useState(currentView === 'dashboard' ? 'dashboard' : 'chat');
  const [userName, setUserName] = useState('用户');
  const [riskPreference, setRiskPreference] = useState('balanced');
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [alertCount, setAlertCount] = useState(0);
  const [showAddInput, setShowAddInput] = useState(false);
  const [newTicker, setNewTicker] = useState('');
  const { subscriptionEmail, portfolioPositions, currentTicker } = useStore();

  useEffect(() => {
    if (currentView === 'dashboard') {
      setActiveTab('dashboard');
    } else if (currentView === 'chat') {
      setActiveTab('chat');
    }
  }, [currentView]);

  const handleAddTicker = async () => {
    const ticker = newTicker.trim().toUpperCase();
    if (!ticker) return;
    try {
      await apiClient.addWatchlist({ user_id: DEFAULT_USER_ID, ticker });
      setNewTicker('');
      setShowAddInput(false);
      await loadUserProfile();
    } catch (error) {
      console.error('Failed to add ticker:', error);
    }
  };

  const handleRemoveTicker = async (ticker: string) => {
    try {
      await apiClient.removeWatchlist({ user_id: DEFAULT_USER_ID, ticker });
      setWatchlist((prev) => prev.filter((item) => item.symbol !== ticker));
    } catch (error) {
      console.error('Failed to remove ticker:', error);
    }
  };

  const loadUserProfile = async () => {
    try {
      const response = await apiClient.getUserProfile(DEFAULT_USER_ID);
      const profile = response?.profile;
      if (!profile) return;

      setUserName(profile.name || '用户');
      setRiskPreference(profile.risk_preference || 'balanced');

      const list = Array.isArray(profile.watchlist) ? profile.watchlist : [];
      if (!list.length) {
        setWatchlist([]);
        return;
      }

      const results = await Promise.all(
        list.slice(0, 6).map(async (ticker: string) => {
          try {
            const priceRes = await apiClient.fetchStockPrice(ticker);
            const payload = priceRes?.data ?? priceRes;
            const data = payload?.data ?? payload;

            let price: string | undefined;
            let change: string | undefined;
            let isUp = true;

            if (typeof data === 'object' && data.price) {
              price = `$${Number(data.price).toFixed(2)}`;
              if (data.change_percent !== undefined) {
                const pct = Number(data.change_percent);
                isUp = pct >= 0;
                change = `${isUp ? '+' : ''}${pct.toFixed(2)}%`;
              }
            }

            return { symbol: ticker, name: ticker, price, change, isUp } as WatchlistItem;
          } catch {
            return { symbol: ticker, name: ticker } as WatchlistItem;
          }
        }),
      );

      setWatchlist(results);
    } catch (error) {
      console.error('Failed to load user profile:', error);
    }
  };

  const loadAlertCount = async () => {
    if (!subscriptionEmail) {
      setAlertCount(0);
      return;
    }
    try {
      const response = await apiClient.listSubscriptions(subscriptionEmail);
      const subscriptions = Array.isArray(response?.subscriptions) ? response.subscriptions : [];
      setAlertCount(subscriptions.length);
    } catch {
      setAlertCount(0);
    }
  };

  useEffect(() => {
    loadUserProfile();
    loadAlertCount();
    const timer = setInterval(() => {
      loadUserProfile();
      loadAlertCount();
    }, 60_000);
    return () => clearInterval(timer);
  }, [subscriptionEmail]);

  return (
    <aside
      data-testid="sidebar"
      className="w-[260px] h-full bg-fin-card border-r border-fin-border flex flex-col p-5 shrink-0 z-20 relative max-lg:w-full max-lg:h-auto max-lg:border-r-0 max-lg:border-b"
    >
      <div className="text-xl font-extrabold text-fin-primary mb-8 flex items-center gap-2">
        <span>📈</span> FinSight Pro
      </div>

      <div className="bg-fin-bg-secondary p-4 rounded-xl mb-5">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 bg-slate-300 rounded-full flex items-center justify-center overflow-hidden">
            <User size={24} className="text-slate-500" />
          </div>
          <div>
            <div className="font-semibold text-fin-text text-sm">{userName}</div>
            <span className="text-[10px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-bold">
              {RISK_LABELS[riskPreference] || '稳健型'}
            </span>
          </div>
        </div>
      </div>

      <nav className="flex flex-col gap-1 flex-1">
        <NavItem
          icon={<MessageSquare size={18} />}
          label="智能对话"
          active={activeTab === 'chat'}
          testId="sidebar-nav-chat"
          onClick={() => {
            setActiveTab('chat');
            onChatClick?.();
          }}
        />

        <NavItem
          icon={<LayoutDashboard size={18} />}
          label="仪表盘"
          active={activeTab === 'dashboard'}
          testId="sidebar-nav-dashboard"
          onClick={() => {
            setActiveTab('dashboard');
            if (!onDashboardClick) return;

            const firstWatchlistSymbol = watchlist[0]?.symbol;
            const firstPositionSymbol = Object.keys(portfolioPositions ?? {})[0];
            const fallbackSymbol = (firstWatchlistSymbol || firstPositionSymbol || currentTicker || '').toString().trim();

            if (fallbackSymbol) {
              onDashboardClick(fallbackSymbol);
              return;
            }

            setShowAddInput(true);
          }}
        />

        <NavItem
          icon={<FileText size={18} />}
          label="研报库"
          active={activeTab === 'reports'}
          onClick={() => setActiveTab('reports')}
        />

        <NavItem
          icon={<Bell size={18} />}
          label="订阅管理"
          active={activeTab === 'alerts'}
          badge={alertCount > 0 ? String(alertCount) : undefined}
          onClick={() => {
            setActiveTab('alerts');
            onSubscribeClick?.();
          }}
        />

        <NavItem
          icon={<Settings size={18} />}
          label="偏好设置"
          active={activeTab === 'settings'}
          onClick={() => {
            setActiveTab('settings');
            onSettingsClick?.();
          }}
        />
      </nav>

      <div className="mt-auto border-t border-fin-border pt-5">
        <div className="flex items-center justify-between mb-3 text-fin-text font-semibold text-sm">
          <span>我的关注 ({watchlist.length})</span>
          <Plus
            size={16}
            className="cursor-pointer hover:text-fin-primary"
            onClick={() => setShowAddInput((prev) => !prev)}
          />
        </div>

        {showAddInput && (
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={newTicker}
              onChange={(event) => setNewTicker(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && handleAddTicker()}
              placeholder="输入股票代码"
              className="flex-1 px-2 py-1 text-sm border border-fin-border rounded bg-fin-bg text-fin-text focus:outline-none focus:border-fin-primary"
              autoFocus
            />
            <button
              type="button"
              onClick={handleAddTicker}
              className="px-2 py-1 text-xs bg-fin-primary text-white rounded hover:opacity-90"
            >
              添加
            </button>
          </div>
        )}

        <div className="space-y-2 max-h-60 overflow-y-auto">
          {watchlist.length > 0 ? (
            watchlist.map((item) => {
              const shares = portfolioPositions[item.symbol.toUpperCase()] || 0;
              return (
                <div
                  key={item.symbol}
                  className="group flex justify-between items-center py-2 px-1 hover:bg-fin-bg-secondary rounded cursor-pointer transition-colors"
                  onClick={() => onDashboardClick?.(item.symbol)}
                >
                  <div className="flex flex-col min-w-0">
                    <span className="font-bold text-fin-text text-sm truncate">{item.symbol}</span>
                    <span className="text-[10px] text-fin-muted truncate">{item.name}</span>
                    {shares > 0 && (
                      <span className="text-[10px] text-fin-primary bg-fin-bg px-1.5 py-0.5 rounded-full w-fit mt-1">
                        持仓 {shares}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <div className="text-right">
                      <div className={`font-medium text-sm ${item.isUp ? 'text-fin-success' : 'text-fin-danger'}`}>
                        {item.price || '--'}
                      </div>
                      <div className={`text-[10px] ${item.isUp ? 'text-fin-success' : 'text-fin-danger'}`}>
                        {item.change || '--'}
                      </div>
                    </div>

                    <X
                      size={14}
                      className="text-fin-muted hover:text-fin-danger opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={(event) => {
                        event.stopPropagation();
                        handleRemoveTicker(item.symbol);
                      }}
                    />
                  </div>
                </div>
              );
            })
          ) : (
            <div className="text-xs text-fin-muted py-2">暂无关注股票</div>
          )}
        </div>
      </div>
    </aside>
  );
};

const NavItem: React.FC<{
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  badge?: string;
  testId?: string;
}> = ({ icon, label, active, onClick, badge, testId }) => (
  <button
    type="button"
    data-testid={testId}
    onClick={onClick}
    className={`
      flex items-center gap-3 px-3 py-3 rounded-lg transition-all duration-200 text-sm text-left
      ${
        active
          ? 'bg-blue-50 text-fin-primary font-medium'
          : 'text-fin-text-secondary hover:bg-fin-bg-secondary hover:text-fin-primary'
      }
    `}
  >
    {icon}
    <span>{label}</span>
    {badge && (
      <span className="ml-auto bg-fin-danger text-white text-[10px] px-1.5 py-0.5 rounded-full">{badge}</span>
    )}
  </button>
);

export default Sidebar;

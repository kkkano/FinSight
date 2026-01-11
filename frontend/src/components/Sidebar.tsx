import React, { useState, useEffect } from 'react';
import { MessageSquare, LayoutDashboard, FileText, Bell, Settings, Plus, User } from 'lucide-react';
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
}

const DEFAULT_USER_ID = 'default_user';

// 风险偏好映射
const RISK_LABELS: Record<string, string> = {
    conservative: '保守型投资者',
    balanced: '稳健型投资者',
    aggressive: '进取型投资者',
};

const Sidebar: React.FC<SidebarProps> = ({ onSettingsClick }) => {
    const [activeTab, setActiveTab] = useState('chat');
    const [userName, setUserName] = useState('用户');
    const [riskPreference, setRiskPreference] = useState('balanced');
    const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
    const [alertCount, setAlertCount] = useState(0);
    const { subscriptionEmail } = useStore();

    // 加载用户画像和 Watchlist
    const loadUserProfile = async () => {
        try {
            const response = await apiClient.getUserProfile(DEFAULT_USER_ID);
            const profile = response?.profile;
            if (profile) {
                setUserName(profile.name || '用户');
                setRiskPreference(profile.risk_preference || 'balanced');
                // 加载 Watchlist 价格
                const list = Array.isArray(profile.watchlist) ? profile.watchlist : [];
                if (list.length > 0) {
                    const results = await Promise.all(
                        list.slice(0, 5).map(async (ticker: string) => {
                            try {
                                const priceRes = await apiClient.fetchStockPrice(ticker);
                                const data = priceRes?.data ?? priceRes;
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
                                return { symbol: ticker, name: ticker, price, change, isUp };
                            } catch {
                                return { symbol: ticker, name: ticker };
                            }
                        })
                    );
                    setWatchlist(results);
                } else {
                    setWatchlist([]);
                }
            }
        } catch (e) {
            console.error('Failed to load user profile:', e);
        }
    };

    // 加载订阅数量
    const loadAlertCount = async () => {
        if (!subscriptionEmail) {
            setAlertCount(0);
            return;
        }
        try {
            const response = await apiClient.listSubscriptions(subscriptionEmail);
            const subs = Array.isArray(response?.subscriptions) ? response.subscriptions : [];
            setAlertCount(subs.length);
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
        }, 60000);
        return () => clearInterval(timer);
    }, [subscriptionEmail]);

    return (
        <div className="w-[260px] h-full bg-fin-card border-r border-fin-border flex flex-col p-5 shrink-0 z-20 relative">
            {/* Logo */}
            <div className="text-xl font-extrabold text-fin-primary mb-8 flex items-center gap-2">
                <span>🐟</span> FinSight Pro
            </div>

            {/* User Profile Widget */}
            <div className="bg-fin-bg-secondary p-4 rounded-xl mb-5">
                <div className="flex items-center gap-3 mb-2">
                    <div className="w-10 h-10 bg-slate-300 rounded-full flex items-center justify-center overflow-hidden">
                        <User size={24} className="text-slate-500" />
                    </div>
                    <div>
                        <div className="font-semibold text-fin-text text-sm">{userName}</div>
                        <span className="text-[10px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-bold">
                            {RISK_LABELS[riskPreference] || '稳健型投资者'}
                        </span>
                    </div>
                </div>
            </div>

            {/* Navigation Menu */}
            <nav className="flex flex-col gap-1 flex-1">
                <NavItem
                    icon={<MessageSquare size={18} />}
                    label="智能对话"
                    active={activeTab === 'chat'}
                    onClick={() => setActiveTab('chat')}
                />
                <NavItem
                    icon={<LayoutDashboard size={18} />}
                    label="仪表盘"
                    active={activeTab === 'dashboard'}
                    onClick={() => setActiveTab('dashboard')}
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
                    onClick={() => setActiveTab('alerts')}
                    badge={alertCount > 0 ? String(alertCount) : undefined}
                />
                <NavItem
                    icon={<Settings size={18} />}
                    label="偏好设置"
                    active={activeTab === 'settings'}
                    onClick={() => {
                        setActiveTab('settings');
                        if (onSettingsClick) onSettingsClick();
                    }}
                />
            </nav>

            {/* Watchlist Mini */}
            <div className="mt-auto border-t border-fin-border pt-5">
                <div className="flex items-center justify-between mb-3 text-fin-text font-semibold text-sm">
                    <span>实时关注 ({watchlist.length})</span>
                    <Plus size={16} className="cursor-pointer hover:text-fin-primary" />
                </div>

                <div className="space-y-2">
                    {watchlist.length > 0 ? (
                        watchlist.map((item) => (
                            <div key={item.symbol} className="flex justify-between items-center py-2 px-1 hover:bg-fin-bg-secondary rounded cursor-pointer transition-colors">
                                <div className="flex flex-col">
                                    <span className="font-bold text-fin-text text-sm">{item.symbol}</span>
                                    <span className="text-[10px] text-fin-muted">{item.name}</span>
                                </div>
                                <div className="text-right">
                                    <div className={`font-medium text-sm ${item.isUp ? 'text-fin-success' : 'text-fin-danger'}`}>
                                        {item.price || '--'}
                                    </div>
                                    <div className={`text-[10px] ${item.isUp ? 'text-fin-success' : 'text-fin-danger'}`}>
                                        {item.change || '--'}
                                    </div>
                                </div>
                            </div>
                        ))
                    ) : (
                        <div className="text-xs text-fin-muted py-2">暂无关注股票</div>
                    )}
                </div>
            </div>
        </div>
    );
};

const NavItem: React.FC<{
    icon: React.ReactNode;
    label: string;
    active: boolean;
    onClick: () => void;
    badge?: string;
}> = ({ icon, label, active, onClick, badge }) => (
    <div
        onClick={onClick}
        className={`
      flex items-center gap-3 px-3 py-3 rounded-lg cursor-pointer transition-all duration-200 text-sm
      ${active
                ? 'bg-blue-50 text-fin-primary font-medium'
                : 'text-fin-text-secondary hover:bg-fin-bg-secondary hover:text-fin-primary'}
    `}
    >
        {icon}
        <span>{label}</span>
        {badge && (
            <span className="ml-auto bg-fin-danger text-white text-[10px] px-1.5 py-0.5 rounded-full">
                {badge}
            </span>
        )}
    </div>
);

export default Sidebar;

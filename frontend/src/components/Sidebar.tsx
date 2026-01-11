import React, { useState } from 'react';
import { MessageSquare, LayoutDashboard, FileText, Bell, Settings, Plus, User } from 'lucide-react';

interface WatchlistItem {
    symbol: string;
    name: string;
    price: string;
    change: string;
    isUp: boolean;
}

interface SidebarProps {
    onSettingsClick?: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ onSettingsClick }) => {
    const [activeTab, setActiveTab] = useState('chat');

    // 模拟数据，后续对接 Context/Store
    const watchlist: WatchlistItem[] = [
        { symbol: 'NVDA', name: 'NVIDIA Corp', price: '$145.20', change: '+2.5%', isUp: true },
        { symbol: 'AAPL', name: 'Apple Inc', price: '$220.15', change: '-0.8%', isUp: false },
    ];

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
                        {/* Placeholder Avatar */}
                        <User size={24} className="text-slate-500" />
                    </div>
                    <div>
                        <div className="font-semibold text-fin-text text-sm">Alex Johnson</div>
                        <span className="text-[10px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-bold">
                            进取型投资者
                        </span>
                    </div>
                </div>
                <div className="text-xs text-fin-muted">
                    上次复盘: 昨晚 22:30
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
                    badge="3"
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
                    <span>实时关注 (Watchlist)</span>
                    <Plus size={16} className="cursor-pointer hover:text-fin-primary" />
                </div>

                <div className="space-y-2">
                    {watchlist.map((item) => (
                        <div key={item.symbol} className="flex justify-between items-center py-2 px-1 hover:bg-fin-bg-secondary rounded cursor-pointer transition-colors">
                            <div className="flex flex-col">
                                <span className="font-bold text-fin-text text-sm">{item.symbol}</span>
                                <span className="text-[10px] text-fin-muted">{item.name}</span>
                            </div>
                            <div className="text-right">
                                <div className={`font-medium text-sm ${item.isUp ? 'text-fin-success' : 'text-fin-danger'}`}>
                                    {item.price}
                                </div>
                                <div className={`text-[10px] ${item.isUp ? 'text-fin-success' : 'text-fin-danger'}`}>
                                    {item.change}
                                </div>
                            </div>
                        </div>
                    ))}
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

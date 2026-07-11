import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bell,
  Command,
  Filter,
  FlaskConical,
  LayoutDashboard,
  LineChart,
  Menu,
  MessageSquare,
  Settings,
  X,
  FileText,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';

import { apiClient } from '../api/client';
import { usePortfolioSummary, buildPositionsMap } from '../hooks/usePortfolioSummary';
import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import { useToast } from './ui';

interface SidebarProps {
  onSettingsClick?: () => void;
  onSubscribeClick?: () => void;
  onDashboardClick?: (symbol: string) => void;
  onChatClick?: () => void;
  onWorkbenchClick?: () => void;
  onCnMarketClick?: () => void;
  currentView?: 'chat' | 'dashboard' | 'workbench' | 'cn-market';
  isMobileOpen?: boolean;
  onMobileOpen?: () => void;
  onMobileClose?: () => void;
}

const readStoredDashboardSymbol = (): string => {
  if (typeof window === 'undefined') return '';
  try {
    const raw = window.localStorage.getItem('fs_dashboard_active_v1');
    const parsed = raw ? JSON.parse(raw) : null;
    return typeof parsed?.symbol === 'string' ? parsed.symbol.trim() : '';
  } catch {
    return '';
  }
};

const Sidebar: React.FC<SidebarProps> = ({
  onSettingsClick,
  onSubscribeClick,
  onDashboardClick,
  onChatClick,
  onWorkbenchClick,
  onCnMarketClick,
  currentView,
  isMobileOpen = false,
  onMobileOpen,
  onMobileClose,
}) => {
  const [alertCount, setAlertCount] = useState(0);
  const { toast } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const { subscriptionEmail, currentTicker, sessionId } = useStore();
  const { data: portfolioData } = usePortfolioSummary(sessionId);
  const portfolioPositions = useMemo(() => buildPositionsMap(portfolioData), [portfolioData]);
  const { watchlist, initWatchlist, activeAsset: lastDashboardAsset } = useDashboardStore();

  const compactMobile = !isMobileOpen;
  const activeKey = location.pathname.startsWith('/screener')
    ? 'screener'
    : location.pathname.startsWith('/backtest')
      ? 'backtest'
      : currentView ?? 'chat';

  const loadAlertCount = useCallback(async () => {
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
  }, [subscriptionEmail]);

  useEffect(() => {
    initWatchlist();
    void loadAlertCount();
  }, [initWatchlist, loadAlertCount]);

  const closeMobile = () => onMobileClose?.();

  const openDashboard = () => {
    if (!onDashboardClick) return;
    const firstPositionSymbol = Object.keys(portfolioPositions ?? {})[0];
    const fallbackSymbol = (
      lastDashboardAsset?.symbol
      || currentTicker
      || readStoredDashboardSymbol()
      || firstPositionSymbol
      || watchlist[0]?.symbol
      || 'AAPL'
    ).toString().trim();

    if (!fallbackSymbol) {
      toast({ type: 'info', title: '还没有可用标的', message: '请先添加股票，例如 AAPL' });
      return;
    }
    onDashboardClick(fallbackSymbol);
    closeMobile();
  };

  return (
    <>
      {isMobileOpen && (
        <div className="fixed inset-0 z-30 bg-black/50 md:hidden" onClick={closeMobile} aria-hidden="true" />
      )}
      <aside
        data-testid="sidebar"
        role="navigation"
        aria-label="主导航栏"
        className={[
          'relative z-40 flex h-full w-[216px] shrink-0 flex-col border-r border-t-border bg-t-surface px-3 py-4 transition-[width] duration-200',
          'max-md:fixed max-md:inset-y-0 max-md:left-0',
          compactMobile ? 'max-md:w-14 max-md:px-2' : 'max-md:w-[216px]',
        ].join(' ')}
      >
        <div className="flex h-9 items-center justify-between px-2">
          <button
            type="button"
            onClick={compactMobile ? onMobileOpen : undefined}
            className="flex min-w-0 items-center gap-2 text-left"
            aria-label={compactMobile ? '展开导航菜单' : 'FinSight 首页'}
            title="FINSIGHT"
          >
            <span className={`${compactMobile ? 'max-md:hidden' : ''} font-mono text-sm font-semibold tracking-[0.12em] text-t-accent`}>
              FINSIGHT
            </span>
            <span className="font-mono font-semibold text-t-accent">▎</span>
            {compactMobile && <Menu size={16} className="hidden text-t-text2 max-md:block" />}
          </button>
          {isMobileOpen && (
            <button
              type="button"
              onClick={closeMobile}
              className="hidden h-9 w-9 items-center justify-center rounded-md text-t-text3 hover:bg-t-hover hover:text-t-text max-md:flex"
              aria-label="收起导航菜单"
            >
              <X size={16} />
            </button>
          )}
        </div>

        <button
          type="button"
          data-testid="sidebar-nav-command-palette"
          onClick={() => {
            window.dispatchEvent(new CustomEvent('finsight:open-command-palette'));
            closeMobile();
          }}
          className={[
            'mt-3 flex h-9 items-center gap-2 rounded-md border border-t-border bg-t-bg px-3 text-[12px] text-t-text3 hover:border-t-accent/50 hover:text-t-text',
            compactMobile ? 'max-md:justify-center max-md:px-0' : '',
          ].join(' ')}
          title="搜索/命令（⌘K）"
        >
          <Command size={16} className="shrink-0" />
          <span className={compactMobile ? 'max-md:hidden' : ''}>搜索/命令…</span>
          <kbd className={`${compactMobile ? 'max-md:hidden' : ''} ml-auto font-mono text-2xs text-t-text3`}>⌘K</kbd>
        </button>

        <nav className="mt-1 flex min-h-0 flex-1 flex-col">
          <NavGroupLabel compact={compactMobile}>工作区</NavGroupLabel>
          <NavItem icon={<MessageSquare size={16} />} label="对话" active={activeKey === 'chat'} compact={compactMobile} testId="sidebar-nav-chat" onClick={() => { onChatClick?.(); closeMobile(); }} />
          <NavItem icon={<LayoutDashboard size={16} />} label="看板" active={activeKey === 'dashboard'} compact={compactMobile} testId="sidebar-nav-dashboard" onClick={openDashboard} />
          <NavItem icon={<FileText size={16} />} label="工作台" active={activeKey === 'workbench'} compact={compactMobile} testId="sidebar-nav-workbench" onClick={() => { onWorkbenchClick?.(); closeMobile(); }} />
          <NavItem icon={<LineChart size={16} />} label="A股市场" active={activeKey === 'cn-market'} compact={compactMobile} testId="sidebar-nav-cn-market" onClick={() => { onCnMarketClick?.(); closeMobile(); }} />

          <NavGroupLabel compact={compactMobile}>工具</NavGroupLabel>
          <NavItem icon={<Filter size={16} />} label="筛选器" active={activeKey === 'screener'} compact={compactMobile} testId="sidebar-nav-screener" onClick={() => { navigate('/screener'); closeMobile(); }} />
          <NavItem icon={<FlaskConical size={16} />} label="回测" active={activeKey === 'backtest'} compact={compactMobile} testId="sidebar-nav-backtest" onClick={() => { navigate('/backtest'); closeMobile(); }} />

          <div className="mt-auto border-t border-t-border pt-2">
            <NavItem icon={<Bell size={16} />} label="订阅与提醒" active={false} compact={compactMobile} testId="sidebar-nav-subscriptions" badge={alertCount > 0 ? String(alertCount) : undefined} onClick={() => { onSubscribeClick?.(); closeMobile(); }} />
            <NavItem icon={<Settings size={16} />} label="设置" active={false} compact={compactMobile} testId="sidebar-nav-settings" onClick={() => { onSettingsClick?.(); closeMobile(); }} />
          </div>
        </nav>
      </aside>
    </>
  );
};

const NavGroupLabel: React.FC<{ compact: boolean; children: React.ReactNode }> = ({ compact, children }) => (
  <div className={`${compact ? 'max-md:hidden' : ''} px-3 pb-1 pt-4 text-2xs uppercase tracking-wider text-t-text3`}>
    {children}
  </div>
);

const NavItem: React.FC<{
  icon: React.ReactNode;
  label: string;
  active: boolean;
  compact: boolean;
  onClick: () => void;
  badge?: string;
  testId?: string;
}> = ({ icon, label, active, compact, onClick, badge, testId }) => (
  <button
    type="button"
    data-testid={testId}
    onClick={onClick}
    aria-current={active ? 'page' : undefined}
    title={label}
    className={[
      'relative flex h-9 w-full items-center gap-3 rounded-md px-3 text-left text-[13px] transition-colors',
      compact ? 'max-md:justify-center max-md:px-0' : '',
      active
        ? '-ml-px border-l-2 border-t-accent bg-t-hover text-t-text'
        : 'text-t-text2 hover:bg-t-hover hover:text-t-text',
    ].join(' ')}
  >
    <span className="shrink-0">{icon}</span>
    <span className={compact ? 'max-md:hidden' : ''}>{label}</span>
    {badge && (
      <span className={`${compact ? 'max-md:absolute max-md:ml-5 max-md:-mt-5 max-md:px-1' : 'ml-auto px-1.5'} rounded-full bg-t-down text-2xs text-white`}>
        {badge}
      </span>
    )}
  </button>
);

export default Sidebar;

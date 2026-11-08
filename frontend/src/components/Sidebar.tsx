import React, { useState } from 'react';
import {
  Command,
  Plus,
  Trash2,
  History,
  Target,
  LayoutDashboard,
  MessageSquare,
  Sun,
  Settings,
  X,
} from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useDashboardStore } from '../store/dashboardStore';
import { useStore } from '../store/useStore';
import { useWatchlist } from '../hooks/useWatchlist';
import { groupConversations } from '../utils/conversationHistory';
import { ConversationDeleteDialog } from './chat/ConversationDeleteDialog';

interface SidebarProps {
  onSettingsClick?: () => void;
  onDashboardClick?: (symbol: string) => void;
  onChatClick?: () => void;
  onHistoryClick?: () => void;
  onTodayClick?: () => void;
  onTrackRecordClick?: () => void;
  currentView?: 'today' | 'chat' | 'dashboard' | 'history' | 'track-record';
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
  onDashboardClick,
  onChatClick,
  onHistoryClick,
  onTodayClick,
  onTrackRecordClick,
  currentView,
  isMobileOpen = false,
  onMobileOpen,
  onMobileClose,
}) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentTicker, sessionId, conversationSummaries, selectConversation, deleteConversation, startNewChat } = useStore();
  const { activeAsset: lastDashboardAsset } = useDashboardStore();
  const { watchlist } = useWatchlist();
  const [deleting, setDeleting] = useState<{ sessionId: string; title: string } | null>(null);
  const groups = groupConversations(conversationSummaries);

  const compactMobile = !isMobileOpen;
  const activeKey = currentView ?? (
    location.pathname.startsWith('/track-record') ? 'track-record' : location.pathname.startsWith('/today')
      ? 'today'
      : location.pathname.startsWith('/history')
        ? 'history'
        : 'chat'
  );


  const closeMobile = () => onMobileClose?.();

  const openDashboard = () => {
    if (!onDashboardClick) return;
    const fallbackSymbol = (
      lastDashboardAsset?.symbol
      || currentTicker
      || readStoredDashboardSymbol()
      || watchlist[0]?.symbol
      || 'AAPL'
    ).toString().trim();

    onDashboardClick(fallbackSymbol);
    closeMobile();
  };

  return (
    <>
      {isMobileOpen && (
        <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={closeMobile} aria-hidden="true" />
      )}
      <aside
        data-testid="sidebar"
        role="navigation"
        aria-label="主导航栏"
        className={[
          'relative z-40 flex h-full w-[240px] shrink-0 flex-col border-r border-t-border px-3 py-4',
          'max-lg:fixed max-lg:inset-y-0 max-lg:left-0',
          compactMobile ? 'max-lg:w-14 max-lg:px-2' : 'max-lg:w-[240px]',
        ].join(' ')}
        style={{ background: 'var(--t-bg-2)' }}
      >
        <div className="flex h-9 items-center justify-between px-2">
          <button
            type="button"
            onClick={compactMobile ? onMobileOpen : undefined}
            className="flex min-w-0 items-center gap-2 text-left"
            aria-label={compactMobile ? '展开导航菜单' : 'FinSight 首页'}
            title="FINSIGHT"
          >
            <span className={`${compactMobile ? 'max-lg:hidden' : ''} text-[15px] font-semibold text-t-text`}>
              FinSight
            </span>
            <img src="/logo.svg?v=8672cb27dc15" alt="" aria-hidden="true" className="h-8 w-8 shrink-0 rounded-md" />
          </button>
          {isMobileOpen && (
            <button
              type="button"
              onClick={closeMobile}
              className="hidden h-9 w-9 items-center justify-center rounded-md text-t-text3 hover:bg-t-hover hover:text-t-text max-lg:flex"
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
            compactMobile ? 'max-lg:justify-center max-lg:px-0' : '',
          ].join(' ')}
          title="搜索/命令（⌘K）"
        >
          <Command size={16} className="shrink-0" />
          <span className={compactMobile ? 'max-lg:hidden' : ''}>搜索/命令…</span>
          <kbd className={`${compactMobile ? 'max-lg:hidden' : ''} ml-auto font-mono text-2xs text-t-text3`}>⌘K</kbd>
        </button>

        <button type="button" className="mt-3 flex min-h-10 items-center justify-center gap-2 rounded-lg border border-t-border bg-t-card text-sm text-t-text hover:border-t-accent/40"
          aria-label="新建对话" onClick={() => { startNewChat(); onChatClick?.(); closeMobile(); }}><Plus size={15} /><span className={compactMobile ? 'max-lg:hidden' : ''}>新对话</span></button>
        <nav className="mt-1 flex min-h-0 flex-1 flex-col">
          <NavGroupLabel compact={compactMobile}>主工作区</NavGroupLabel>
          <NavItem icon={<Sun size={16} />} label="今日" active={activeKey === 'today'} compact={compactMobile} testId="sidebar-nav-today" onClick={() => { onTodayClick?.(); closeMobile(); }} />
          <NavItem icon={<LayoutDashboard size={16} />} label="看板" active={activeKey === 'dashboard'} compact={compactMobile} testId="sidebar-nav-dashboard" onClick={openDashboard} />
          <NavItem icon={<MessageSquare size={16} />} label="对话" active={activeKey === 'chat'} compact={compactMobile} testId="sidebar-nav-chat" onClick={() => { onChatClick?.(); closeMobile(); }} />
          <NavItem icon={<History size={16} />} label="历史" active={activeKey === 'history'} compact={compactMobile} testId="sidebar-nav-history" onClick={() => { onHistoryClick?.(); closeMobile(); }} />
          <NavItem icon={<Target size={16} />} label="战绩" active={activeKey === 'track-record'} compact={compactMobile} testId="sidebar-nav-track-record" onClick={() => { if (onTrackRecordClick) onTrackRecordClick(); else navigate('/track-record'); closeMobile(); }} />

          {groups.length > 0 && <div className={compactMobile ? 'mt-4 min-h-0 flex-1 overflow-y-auto max-lg:hidden' : 'mt-4 min-h-0 flex-1 overflow-y-auto'} data-testid="conversation-rail">
            <div className="px-3 pb-2 text-xs text-t-text3">最近对话</div>
            <div role="list" aria-label="会话列表">
              {groups.map((group) => <div key={group.label}><p className="px-2.5 pb-1 pt-3 text-xs text-t-text3">{group.label}</p>{group.items.map((conversation) => <div role="listitem" key={conversation.sessionId} data-testid="conversation-item"
                data-session-id={conversation.sessionId} data-active={conversation.sessionId === sessionId ? 'true' : 'false'}
                className={'group flex min-h-9 items-center rounded-[7px] ' + (conversation.sessionId === sessionId ? 'bg-t-surface shadow-sm' : 'hover:bg-t-hover')}>
                <button type="button" className="min-w-0 flex-1 truncate px-2.5 py-[7px] text-left text-[13px] text-t-text2"
                  title={conversation.title} onClick={() => { selectConversation(conversation.sessionId); closeMobile(); }}>{conversation.title || '新对话'}</button>
                <button type="button" className="mr-1 rounded-md p-2 text-t-text3 opacity-0 hover:text-fin-danger group-hover:opacity-100 focus:opacity-100 max-lg:opacity-100"
                  aria-label="删除会话" title="删除会话" data-testid="conversation-delete" onClick={() => setDeleting(conversation)}><Trash2 size={14} /></button>
              </div>)}</div>)}
            </div>
          </div>}
          <div className="mt-auto border-t border-t-border pt-2">
            {onSettingsClick && <NavItem icon={<Settings size={16} />} label="设置" active={false} compact={compactMobile} testId="sidebar-nav-settings" onClick={() => { onSettingsClick(); closeMobile(); }} />}
          </div>
        </nav>
      </aside>
      <ConversationDeleteDialog title={deleting?.title ?? null} onCancel={() => setDeleting(null)}
        onConfirm={() => { if (deleting) deleteConversation(deleting.sessionId); setDeleting(null); }} />
    </>
  );
};

const NavGroupLabel: React.FC<{ compact: boolean; children: React.ReactNode }> = ({ compact, children }) => (
  <div className={`${compact ? 'max-lg:hidden' : ''} px-3 pb-1 pt-4 text-xs text-t-text3`}>
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
      compact ? 'max-lg:justify-center max-lg:px-0' : '',
      active
        ? 'bg-t-card font-medium text-t-text shadow-sm'
        : 'text-t-text2 hover:bg-t-hover hover:text-t-text',
    ].join(' ')}
  >
    <span className="shrink-0">{icon}</span>
    <span className={compact ? 'max-lg:hidden' : ''}>{label}</span>
    {badge && (
      <span className={`${compact ? 'max-lg:absolute max-lg:ml-5 max-lg:-mt-5 max-lg:px-1' : 'ml-auto px-1.5'} rounded-full bg-t-down text-2xs text-white`}>
        {badge}
      </span>
    )}
  </button>
);

export default Sidebar;

import { useEffect, useState } from 'react';
import { ChatList } from './components/ChatList';
import Sidebar from './components/Sidebar';
import { ChatInput } from './components/ChatInput';
import { SettingsModal } from './components/SettingsModal';
import { Settings, Sun, Moon } from 'lucide-react';
import { useStore } from './store/useStore';
import { apiClient } from './api/client';
import { RightPanel } from './components/RightPanel';

function App() {
  const [isChartPanelExpanded, setIsChartPanelExpanded] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [userCollapsed, setUserCollapsed] = useState(false);
  const { currentTicker, messages, theme, setTheme, layoutMode } = useStore();

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

  return (
    <div className="flex h-screen w-screen bg-fin-bg text-fin-text font-mono overflow-hidden">
      {/* 1. Sidebar (Fixed width) */}
      <Sidebar onSettingsClick={() => setIsSettingsOpen(true)} />

      {/* 2. Main Workspace (Flex fill) */}
      <div className="flex-1 flex flex-col h-full overflow-hidden relative">
        {/* Header */}
        <header className="h-[60px] bg-fin-card border-b border-fin-border flex items-center justify-between px-6 shrink-0">
          <div className="flex gap-6 text-xs text-fin-text font-medium">
            <span className="flex items-center gap-1">
              🇺🇸 S&P 500: <span className="text-fin-success">+0.4%</span>
            </span>
            <span className="flex items-center gap-1">
              🇨🇳 沪深300: <span className="text-fin-danger">-0.2%</span>
            </span>
            <span className="flex items-center gap-1">
              🌕 黄金: <span className="text-fin-success">+0.1%</span>
            </span>
            <span className="flex items-center gap-1">
              ₿ BTC: <span className="text-fin-warning">$98,500</span>
            </span>
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

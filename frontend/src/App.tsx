import { useEffect, useState } from 'react';
import { ChatList } from './components/ChatList';
import { ChatInput } from './components/ChatInput';
import { StockChart } from './components/StockChart';
import { SettingsModal } from './components/SettingsModal';
import { CandlestickChart, ChevronRight, ChevronLeft, Settings, Download, Sun, Moon } from 'lucide-react';
import { useStore } from './store/useStore';
import { apiClient } from './api/client';

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
    <div className="relative h-screen w-screen bg-fin-bg text-fin-text font-mono overflow-hidden">
      {/* 背景光晕 */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -left-24 -top-10 h-72 w-72 rounded-full bg-fin-primary opacity-30 blur-[140px]" />
        <div className="absolute right-[-120px] bottom-[-80px] h-80 w-80 rounded-full bg-trend-down opacity-25 blur-[160px]" />
      </div>

      {/* 主框架：根据布局模式切换宽度 */}
      <div className="relative z-10 flex h-full w-full justify-center overflow-hidden">
        <div
          className={`flex h-full w-full ${
            layoutMode === 'centered'
              ? 'max-w-6xl mx-auto px-4'
              : 'max-w-[120rem] mx-auto px-6'
          }`}
        >
          {/* Left: Chat Panel */}
          <div
            className={`flex h-full flex-col bg-fin-bg/98 z-10 transition-all duration-300 ${
              isChartPanelExpanded
                ? 'w-full md:w-[420px] lg:w-[460px] border-r border-fin-border/80'
                : 'w-full flex-1 max-w-4xl mx-auto border-r border-fin-border/80'
            }`}
          >
            {/* Header */}
            <header className="flex items-center justify-between px-4 py-3 border-b border-fin-border/80 bg-fin-bg/95 backdrop-blur-md">
              <div className="flex items-center space-x-2">
                <div className="bg-fin-primary p-1.5 rounded-lg shadow-md shadow-fin-primary/40">
                  <CandlestickChart size={20} className="text-white" />
                </div>
                <div className="flex flex-col">
                  <h1 className="font-bold text-lg tracking-tight">FinSight AI</h1>
                  <span className="text-[11px] text-fin-muted tracking-wide uppercase">
                    Conversational Market Intelligence
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                  className="p-1.5 rounded-full border border-fin-border/60 bg-fin-panel/80 hover:-translate-y-0.5 hover:bg-fin-border transition-all duration-200 shadow-sm"
                  title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                  {theme === 'dark' ? <Sun size={16} className="text-fin-muted" /> : <Moon size={16} className="text-fin-muted" />}
                </button>
                <button
                  onClick={async () => {
                    try {
                      const formattedMessages = messages.map((msg) => ({
                        role: msg.role,
                        content: msg.content,
                        timestamp: new Date(msg.timestamp).toLocaleString('zh-CN'),
                      }));

                      const pdfBlob = await apiClient.exportPDF(formattedMessages);
                      const url = window.URL.createObjectURL(pdfBlob);
                      const a = document.createElement('a');
                      a.href = url;
                      a.download = `finsight_export_${new Date().toISOString().split('T')[0]}.pdf`;
                      document.body.appendChild(a);
                      a.click();
                      document.body.removeChild(a);
                      window.URL.revokeObjectURL(url);
                    } catch (error) {
                      console.error('Export PDF failed:', error);
                      alert('Export PDF failed, please try again.');
                    }
                  }}
                  className="p-1.5 hover:bg-fin-border rounded transition-colors"
                  title="Export PDF"
                >
                  <Download size={16} className="text-fin-muted" />
                </button>
                <button
                  onClick={() => setIsSettingsOpen(true)}
                  className="p-1.5 hover:bg-fin-border rounded transition-colors"
                  title="Settings"
                >
                  <Settings size={16} className="text-fin-muted" />
                </button>
                <div className="text-[10px] px-2 py-1 bg-fin-panel/80 border border-fin-border/80 rounded-full text-fin-muted tracking-wide">
                  v1.0 · BETA
                </div>
              </div>
            </header>

            {/* Settings Modal */}
            <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />

            {/* Chat Area */}
            <div className="flex-1 flex flex-col overflow-hidden">
              <ChatList />
              <ChatInput />
            </div>
          </div>

          {/* Right: Visualization Panel */}
          {isChartPanelExpanded && (
            <div className="flex flex-1 flex-col bg-fin-bg relative transition-all duration-300">
              {/* 折叠按钮 */}
              <button
                onClick={() => {
                  setIsChartPanelExpanded(false);
                }}
                onMouseDown={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                }}
                className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-full z-50 p-2 bg-fin-panel border border-fin-border rounded-l-lg hover:bg-fin-primary hover:text-white transition-all shadow-lg cursor-pointer"
                title="Collapse chart"
              >
                <ChevronRight size={16} />
              </button>

              {/* 背景纹理 */}
              <div
                className="absolute inset-0 opacity-[0.02] pointer-events-none"
                style={{ backgroundImage: 'radial-gradient(#a1a1aa 1px, transparent 1px)', backgroundSize: '24px 24px' }}
              />

              <main className="flex-1 p-6 overflow-hidden relative z-0">
                <div className="h-full w-full bg-fin-panel border border-fin-border rounded-2xl shadow-2xl overflow-hidden flex flex-col">
                  {/* Chart Header */}
                  <div className="h-14 border-b border-fin-border flex items-center justify-between px-4 bg-gradient-to-r from-fin-panel/80 to-fin-panel/50 backdrop-blur-sm">
                    <div className="flex items-center gap-3">
                      <div className="w-1 h-6 bg-fin-primary rounded-full" />
                      <span className="text-sm font-semibold text-fin-text uppercase tracking-wider">
                        Market Data Visualization
                      </span>
                    </div>
                <button
                  onClick={() => {
                    setIsChartPanelExpanded(false);
                    setUserCollapsed(true);
                  }}
                  className="p-2 hover:bg-fin-primary hover:text-white rounded-lg transition-all group cursor-pointer"
                  title="Collapse chart"
                >
                  <ChevronRight size={16} className="text-fin-muted group-hover:text-white transition-colors" />
                    </button>
                  </div>

                  {/* Chart Content */}
                  <div className="flex-1 relative">
                    <StockChart />
                  </div>
                </div>
              </main>
            </div>
          )}
        </div>

        {/* 当图表收起时，显示展开按钮 */}
        <button
          onClick={() => {
            const next = !isChartPanelExpanded;
            setIsChartPanelExpanded(next);
            if (!next) setUserCollapsed(true);
            else setUserCollapsed(false);
          }}
          className="flex fixed right-0 top-1/2 -translate-y-1/2 z-20 p-2 bg-fin-panel border border-fin-border rounded-l-lg hover:bg-fin-border transition-colors"
          title={isChartPanelExpanded ? 'Collapse chart' : 'Expand chart'}
        >
          {isChartPanelExpanded ? (
            <ChevronRight size={16} className="text-fin-muted" />
          ) : (
            <ChevronLeft size={16} className="text-fin-muted" />
          )}
        </button>
      </div>
    </div>
  );
}

export default App;

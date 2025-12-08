import { useEffect, useRef, useState } from 'react';
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
  const { currentTicker, messages, theme, setTheme } = useStore();

  // 当生成新图表时自动展开（只�?currentTicker 变化时，不是 isChartPanelExpanded 变化时）
  const prevTickerRef = useRef<string | null>(null);
  useEffect(() => {
    // 只有�?currentTicker 发生变化（新图表）时才自动展开
    if (currentTicker && currentTicker !== prevTickerRef.current) {
      prevTickerRef.current = currentTicker;
      if (!isChartPanelExpanded) {
        setIsChartPanelExpanded(true);
      }
    }
  }, [currentTicker]); // 只依�?currentTicker，不依赖 isChartPanelExpanded

  return (
    <div className="relative h-screen w-screen bg-fin-bg text-fin-text font-mono overflow-hidden">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -left-24 -top-10 h-72 w-72 rounded-full bg-fin-primary opacity-30 blur-[140px]" />
        <div className="absolute right-[-120px] bottom-[-80px] h-80 w-80 rounded-full bg-trend-down opacity-25 blur-[160px]" />
      </div>

      <div className="relative z-10 flex h-full w-full overflow-hidden">
        {/* Left: Chat Panel - 当图表收起时占据更多空间并居�?*/}
        <div className={`flex h-full flex-col bg-fin-bg z-10 shadow-xl transition-all duration-300 ${
        isChartPanelExpanded
          ? 'w-full md:w-[450px] lg:w-[500px] border-r border-fin-border'
          : 'w-full flex-1 max-w-5xl mx-auto border-x border-fin-border'
      }`}>
        {/* Header */}
        <header className="flex items-center justify-between p-4 border-b border-fin-border bg-fin-bg/80 backdrop-blur-md">
          <div className="flex items-center space-x-2">
            <div className="bg-fin-primary p-1.5 rounded-lg">
              <CandlestickChart size={20} className="text-white" />
            </div>
            <h1 className="font-bold text-lg tracking-tight">FinSight AI</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="p-1.5 rounded-full border border-fin-border/60 bg-fin-panel/70 hover:-translate-y-0.5 hover:bg-fin-border transition-all duration-200 shadow-sm"
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? <Sun size={16} className="text-fin-muted" /> : <Moon size={16} className="text-fin-muted" />}
            </button>
            <button
              onClick={async () => {
                try {
                  // Format messages for PDF export
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
            <div className="text-xs px-2 py-1 bg-fin-panel border border-fin-border rounded text-fin-muted">
              v1.0
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

      {/* Right: Visualization Panel - 可收�?展开 */}
      {isChartPanelExpanded && (
      <div className="hidden md:flex flex-1 flex-col bg-fin-bg relative transition-all duration-300">
        {/* 收起/展开按钮 - 固定在左侧边缘，确保可见和可点击 */}
        <button
          onClick={() => {
            console.log('[App] Collapse chart panel');
            setIsChartPanelExpanded(false);
          }}
          onMouseDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          
          title="Collapse chart"
        >
          <ChevronRight size={16} />
        </button>

        {/* Background Pattern */}
        <div className="absolute inset-0 opacity-[0.02] pointer-events-none"
             style={{ backgroundImage: 'radial-gradient(#a1a1aa 1px, transparent 1px)', backgroundSize: '24px 24px' }}>
        </div>

        <main className="flex-1 p-6 overflow-hidden relative z-0">
          <div className="h-full w-full bg-fin-panel border border-fin-border rounded-2xl shadow-2xl overflow-hidden flex flex-col">
            {/* Chart Header - 带右箭头 */}
            <div className="h-14 border-b border-fin-border flex items-center justify-between px-4 bg-gradient-to-r from-fin-panel/80 to-fin-panel/50 backdrop-blur-sm">
              <div className="flex items-center gap-3">
                <div className="w-1 h-6 bg-fin-primary rounded-full"></div>
                <span className="text-sm font-semibold text-fin-text uppercase tracking-wider">Market Data Visualization</span>
              </div>
              <button
                onClick={() => {
                  console.log('[App] Collapse chart panel from header');
                  setIsChartPanelExpanded(false);
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

      {/* 当图表收起时，显示展开按钮 */}
      {!isChartPanelExpanded && (
        <button
          onClick={() => setIsChartPanelExpanded(true)}
          className="hidden md:flex fixed right-0 top-1/2 -translate-y-1/2 z-20 p-2 bg-fin-panel border border-fin-border rounded-l-lg hover:bg-fin-border transition-colors"
          title="Expand chart"
        >
          <ChevronLeft size={16} className="text-fin-muted" />
        </button>
      )}
      </div>
    </div>
  );
}

export default App;

import { useState, useCallback } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { WorkspaceShell } from './components/layout/WorkspaceShell';
import { ToastProvider } from './components/ui';
import { CommandPalette } from './components/CommandPalette';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';

const decodeSymbolParam = (raw?: string): string | null => {
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
};

function ChatRoute() {
  const navigate = useNavigate();
  const location = useLocation();
  const searchParams = new URLSearchParams(location.search);
  const reportId = searchParams.get('report_id') || null;

  return (
    <WorkspaceShell
      view="chat"
      dashboardSymbol={null}
      initialReportId={reportId}
      navigateToChat={() => navigate('/chat')}
      navigateToDashboard={(symbol) => navigate(`/dashboard/${encodeURIComponent(symbol)}`)}
      navigateToWorkbench={() => navigate('/workbench')}
    />
  );
}

function DashboardRoute() {
  const navigate = useNavigate();
  const { symbol } = useParams();
  return (
    <WorkspaceShell
      view="dashboard"
      dashboardSymbol={decodeSymbolParam(symbol)}
      navigateToChat={() => navigate('/chat')}
      navigateToDashboard={(nextSymbol) => navigate(`/dashboard/${encodeURIComponent(nextSymbol)}`)}
      navigateToWorkbench={() => navigate('/workbench')}
    />
  );
}

function WorkbenchRoute() {
  const navigate = useNavigate();
  return (
    <WorkspaceShell
      view="workbench"
      dashboardSymbol={null}
      navigateToChat={() => navigate('/chat')}
      navigateToDashboard={(nextSymbol) => navigate(`/dashboard/${encodeURIComponent(nextSymbol)}`)}
      navigateToWorkbench={() => navigate('/workbench')}
    />
  );
}

function RootRedirect() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const symbol = params.get('symbol');

  if (symbol && symbol.trim()) {
    return <Navigate to={{ pathname: `/dashboard/${encodeURIComponent(symbol.trim())}`, search: '' }} replace />;
  }
  return <Navigate to={{ pathname: '/chat', search: '' }} replace />;
}

function App() {
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  const handleToggleCommandPalette = useCallback(() => {
    setIsCommandPaletteOpen((prev) => !prev);
  }, []);

  const handleCloseCommandPalette = useCallback(() => {
    setIsCommandPaletteOpen(false);
  }, []);

  // 注册全局键盘快捷键
  useKeyboardShortcuts({
    onToggleCommandPalette: handleToggleCommandPalette,
    isCommandPaletteOpen,
    onCloseCommandPalette: handleCloseCommandPalette,
  });

  return (
    <ToastProvider>
      {/* Skip-navigation link: hidden by default, visible on keyboard focus */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[9999] focus:px-4 focus:py-2 focus:bg-fin-primary focus:text-white focus:rounded-lg focus:outline-none focus:ring-2 focus:ring-white"
      >
        跳转到主要内容
      </a>
      <Routes>
        <Route path="/" element={<RootRedirect />} />
        <Route path="/chat" element={<ChatRoute />} />
        <Route path="/workbench" element={<WorkbenchRoute />} />
        <Route path="/dashboard" element={<DashboardRoute />} />
        <Route path="/dashboard/:symbol" element={<DashboardRoute />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>

      {/* 全局命令面板 */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={handleCloseCommandPalette}
      />
    </ToastProvider>
  );
}

export default App;

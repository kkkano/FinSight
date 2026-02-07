import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { WorkspaceShell } from './components/layout/WorkspaceShell';

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
  return (
    <WorkspaceShell
      view="chat"
      dashboardSymbol={null}
      navigateToChat={() => navigate('/chat')}
      navigateToDashboard={(symbol) => navigate(`/dashboard/${encodeURIComponent(symbol)}`)}
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
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/chat" element={<ChatRoute />} />
      <Route path="/dashboard" element={<DashboardRoute />} />
      <Route path="/dashboard/:symbol" element={<DashboardRoute />} />
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  );
}

export default App;


import { useState, useCallback, useEffect, type ReactElement } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { WorkspaceShell } from './components/layout/WorkspaceShell';
import { WelcomePage } from './components/welcome/WelcomePage';
import { Phase24PanelsPage } from './components/labs/Phase24PanelsPage';
import { ToastProvider } from './components/ui';
import { CommandPalette } from './components/CommandPalette';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import { getSupabaseClient } from './api/supabaseClient';
import { buildAnonymousSessionId, buildUserSessionId, useStore } from './store/useStore';

const WELCOME_GATE_KEY = 'finsight-welcome-gate-passed';

const hasWelcomeGatePassed = (): boolean => {
  if (typeof window === 'undefined') return false;
  return window.sessionStorage.getItem(WELCOME_GATE_KEY) === '1';
};

const markWelcomeGatePassed = (): void => {
  if (typeof window === 'undefined') return;
  window.sessionStorage.setItem(WELCOME_GATE_KEY, '1');
};

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

function EntryGuard({ children }: { children: ReactElement }) {
  const authIdentity = useStore((state) => state.authIdentity);
  const entryMode = useStore((state) => state.entryMode);
  const location = useLocation();
  const hash = String(location.hash || '').toLowerCase();
  const searchParams = new URLSearchParams(location.search);

  const isAuthCallback =
    hash.includes('access_token=')
    || hash.includes('type=magiclink')
    || hash.includes('type=recovery')
    || searchParams.has('code');

  if (isAuthCallback) return children;

  const hasEntryAccess =
    hasWelcomeGatePassed() && (Boolean(authIdentity?.userId) || entryMode === 'anonymous' || entryMode === 'authenticated');
  if (hasEntryAccess) return children;

  const from = `${location.pathname}${location.search}`;
  return <Navigate to={`/welcome?from=${encodeURIComponent(from)}`} replace />;
}

function RootRedirect() {
  return <Navigate to={{ pathname: '/welcome', search: '' }} replace />;
}

function WelcomeRoute() {
  return <WelcomePage />;
}

function PhaseLabsRoute() {
  return <Phase24PanelsPage />;
}

function App() {
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const setAuthIdentity = useStore((state) => state.setAuthIdentity);
  const setEntryMode = useStore((state) => state.setEntryMode);
  const setSessionId = useStore((state) => state.setSessionId);
  const setSubscriptionEmail = useStore((state) => state.setSubscriptionEmail);

  useEffect(() => {
    const client = getSupabaseClient();
    if (!client) {
      setAuthIdentity(null);
      return;
    }

    let isMounted = true;
    const applySession = (session: { user?: { id?: string; email?: string | null } } | null | undefined) => {
      if (!isMounted) return;

      const user = session?.user;
      const userId = String(user?.id || '').trim();
      const email = user?.email ? String(user.email).trim() : null;

      if (userId) {
        markWelcomeGatePassed();
        setAuthIdentity({ userId, email });
        setEntryMode('authenticated');
        setSessionId(buildUserSessionId(userId));
        if (email) setSubscriptionEmail(email);
        return;
      }

      setAuthIdentity(null);
      const currentSessionId = useStore.getState().sessionId;
      if (!String(currentSessionId || '').startsWith('public:anonymous:')) {
        setSessionId(buildAnonymousSessionId());
      }
    };

    client.auth
      .getSession()
      .then(({ data }) => {
        applySession(data.session as { user?: { id?: string; email?: string | null } } | null);
      })
      .catch(() => {
        applySession(null);
      });

    const { data: listener } = client.auth.onAuthStateChange((_event, session) => {
      applySession(session as { user?: { id?: string; email?: string | null } } | null);
    });

    return () => {
      isMounted = false;
      listener.subscription.unsubscribe();
    };
  }, [setAuthIdentity, setEntryMode, setSessionId, setSubscriptionEmail]);

  const handleToggleCommandPalette = useCallback(() => {
    setIsCommandPaletteOpen((prev) => !prev);
  }, []);

  const handleCloseCommandPalette = useCallback(() => {
    setIsCommandPaletteOpen(false);
  }, []);

  useKeyboardShortcuts({
    onToggleCommandPalette: handleToggleCommandPalette,
    isCommandPaletteOpen,
    onCloseCommandPalette: handleCloseCommandPalette,
  });

  return (
    <ToastProvider>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[9999] focus:px-4 focus:py-2 focus:bg-fin-primary focus:text-white focus:rounded-lg focus:outline-none focus:ring-2 focus:ring-white"
      >
        跳转到主要内容
      </a>

      <Routes>
        <Route path="/" element={<RootRedirect />} />
        <Route path="/welcome" element={<WelcomeRoute />} />
        <Route path="/chat" element={<EntryGuard><ChatRoute /></EntryGuard>} />
        <Route path="/workbench" element={<EntryGuard><WorkbenchRoute /></EntryGuard>} />
        <Route path="/phase-labs" element={<EntryGuard><PhaseLabsRoute /></EntryGuard>} />
        <Route path="/dashboard" element={<EntryGuard><DashboardRoute /></EntryGuard>} />
        <Route path="/dashboard/:symbol" element={<EntryGuard><DashboardRoute /></EntryGuard>} />
        <Route path="*" element={<Navigate to="/welcome" replace />} />
      </Routes>

      <CommandPalette isOpen={isCommandPaletteOpen} onClose={handleCloseCommandPalette} />
    </ToastProvider>
  );
}

export default App;

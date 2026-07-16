import { ArrowRight, Mail, Moon, Sun } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { getSupabaseClient, isSupabaseAuthConfigured } from '../../api/supabaseClient';
import { buildAnonymousSessionId, buildUserSessionId, useStore } from '../../store/useStore';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { useToast } from '../ui';

const WELCOME_GATE_KEY = 'finsight-welcome-gate-passed';

const markWelcomeGatePassed = (): void => {
  window.sessionStorage.setItem(WELCOME_GATE_KEY, '1');
};

const resolveDestination = (from: string | null): string => {
  const value = String(from || '').trim();
  if (!value.startsWith('/') || value.startsWith('/welcome')) return '/dashboard/AAPL';
  return value;
};

const isAuthenticatedDestination = (path: string): boolean =>
  path === '/chat' || path.startsWith('/chat?') || path === '/history' || path.startsWith('/history?');

export function WelcomePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();
  const {
    authIdentity,
    theme,
    setTheme,
    setAuthIdentity,
    setEntryMode,
    setSessionId,
  } = useStore();
  const [email, setEmail] = useState(authIdentity?.email || '');
  const [otpCode, setOtpCode] = useState('');
  const [codeSent, setCodeSent] = useState(false);
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);

  const destination = useMemo(
    () => resolveDestination(new URLSearchParams(location.search).get('from')),
    [location.search],
  );
  const supabaseReady = useMemo(() => isSupabaseAuthConfigured(), []);

  const enterAuthenticated = (userId: string, userEmail: string | null) => {
    markWelcomeGatePassed();
    setAuthIdentity({ userId, email: userEmail });
    setEntryMode('authenticated');
    setSessionId(buildUserSessionId(userId));
    navigate(destination, { replace: true });
  };

  const enterReadOnly = () => {
    markWelcomeGatePassed();
    setAuthIdentity(null);
    setEntryMode('anonymous');
    setSessionId(buildAnonymousSessionId());
    navigate(isAuthenticatedDestination(destination) ? '/dashboard/AAPL' : destination, { replace: true });
  };

  const sendCode = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (!/^\S+@\S+\.\S+$/.test(normalizedEmail)) {
      toast({ type: 'error', title: '请输入有效邮箱' });
      return;
    }
    const client = getSupabaseClient();
    if (!client) {
      toast({ type: 'error', title: '登录服务未配置' });
      return;
    }
    setSending(true);
    try {
      const { error } = await client.auth.signInWithOtp({
        email: normalizedEmail,
        options: { shouldCreateUser: true },
      });
      if (error) throw error;
      setCodeSent(true);
      toast({ type: 'success', title: '验证码已发送' });
    } catch (error) {
      toast({
        type: 'error',
        title: '发送失败',
        message: error instanceof Error ? error.message : '请稍后重试',
      });
    } finally {
      setSending(false);
    }
  };

  const verifyCode = async () => {
    const client = getSupabaseClient();
    const normalizedEmail = email.trim().toLowerCase();
    const token = otpCode.trim();
    if (!client || !normalizedEmail || !token) return;
    setVerifying(true);
    try {
      const { data, error } = await client.auth.verifyOtp({
        email: normalizedEmail,
        token,
        type: 'email',
      });
      if (error) throw error;
      const userId = String(data.user?.id || data.session?.user?.id || '').trim();
      if (!userId) throw new Error('登录响应缺少用户身份');
      enterAuthenticated(userId, data.user?.email || data.session?.user?.email || normalizedEmail);
    } catch (error) {
      toast({
        type: 'error',
        title: '验证码无效',
        message: error instanceof Error ? error.message : '请检查后重试',
      });
    } finally {
      setVerifying(false);
    }
  };

  return (
    <main className="min-h-screen bg-t-bg text-t-text">
      <header className="flex h-14 items-center justify-between border-b border-t-border px-5">
        <div className="font-mono text-sm font-semibold text-t-accent">FinSight</div>
        <button
          type="button"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className="flex h-9 w-9 items-center justify-center rounded border border-t-border text-t-text2 hover:text-t-text"
          aria-label="切换主题"
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </header>

      <section className="mx-auto grid min-h-[calc(100vh-3.5rem)] max-w-5xl content-center gap-10 px-5 py-10 md:grid-cols-[1fr_360px] md:items-center">
        <div>
          <h1 className="text-4xl font-semibold leading-tight text-t-text">FinSight</h1>
          <p className="mt-4 max-w-xl text-base leading-7 text-t-text2">
            可信行情、可验证的 AI 判断与证据化研究。
          </p>
          <div className="mt-8 grid max-w-xl gap-px overflow-hidden rounded border border-t-border bg-t-border sm:grid-cols-3">
            {['真实行情与指标', 'AI Prediction', 'Chat 与报告历史'].map((label) => (
              <div key={label} className="bg-t-surface px-4 py-4 text-sm text-t-text2">{label}</div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-t-border bg-t-surface p-5 shadow-sm">
          <h2 className="text-base font-semibold">登录</h2>
          {authIdentity?.userId ? (
            <div className="mt-4 space-y-3">
              <p className="truncate text-sm text-t-text2">{authIdentity.email || authIdentity.userId}</p>
              <Button className="w-full justify-center" onClick={() => enterAuthenticated(authIdentity.userId, authIdentity.email)}>
                继续使用 <ArrowRight size={15} />
              </Button>
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              <Input
                label="邮箱"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="name@example.com"
                autoComplete="email"
              />
              <Button
                className="w-full justify-center"
                onClick={() => void sendCode()}
                disabled={sending || !supabaseReady}
              >
                <Mail size={14} /> {sending ? '发送中' : '发送验证码'}
              </Button>
              {codeSent && (
                <>
                  <Input
                    label="验证码"
                    value={otpCode}
                    onChange={(event) => setOtpCode(event.target.value)}
                    autoComplete="one-time-code"
                  />
                  <Button
                    variant="secondary"
                    className="w-full justify-center"
                    onClick={() => void verifyCode()}
                    disabled={verifying || !otpCode.trim()}
                  >
                    {verifying ? '验证中' : '验证并登录'}
                  </Button>
                </>
              )}
              <div className="flex items-center gap-3 py-1 text-xs text-t-text3">
                <span className="h-px flex-1 bg-t-border" /> 或 <span className="h-px flex-1 bg-t-border" />
              </div>
              <Button variant="secondary" className="w-full justify-center" onClick={enterReadOnly}>
                浏览只读行情
              </Button>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

import { useEffect, useMemo, useState } from 'react';
import { CircleAlert, Mail, Moon, Sun } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getSupabaseClient, isSupabaseAuthConfigured } from '../../api/supabaseClient';
import { useMarketQuotes } from '../../hooks/useMarketQuotes';
import { buildAnonymousSessionId, useStore } from '../../store/useStore';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { useToast } from '../ui';

const isValidEmail = (value: string): boolean => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
const WELCOME_GATE_KEY = 'finsight-welcome-gate-passed';

const markWelcomeGatePassed = (): void => {
  if (typeof window === 'undefined') return;
  window.sessionStorage.setItem(WELCOME_GATE_KEY, '1');
};

const resolveFallbackPath = (from: string | null): string => {
  const raw = String(from || '').trim();
  if (!raw) return '/chat';
  if (!raw.startsWith('/')) return '/chat';
  if (raw.startsWith('/welcome')) return '/chat';
  return raw;
};

const CAPABILITIES = [
  '价格分析',
  '新闻研报',
  '基本面',
  '技术面',
  '宏观经济',
  '风险评估',
  '深度搜索',
  'RAG 检索',
  '邮件预警',
];

const METRIC_CARDS = [
  { label: '智能体数', value: '7', change: '并行执行' },
  { label: '管线节点', value: '18', change: 'LangGraph' },
  { label: '仪表盘', value: '6', change: '标签页' },
];

const FALLBACK_TICKERS = [
  { label: 'AAPL', price: '189.84', pct: '+1.2%', up: true },
  { label: 'MSFT', price: '420.55', pct: '+0.8%', up: true },
  { label: 'NVDA', price: '875.28', pct: '+2.1%', up: true },
  { label: 'TSLA', price: '175.32', pct: '-1.5%', up: false },
  { label: '600519.SS', price: '1688.00', pct: '+0.6%', up: true },
  { label: 'GOOGL', price: '174.15', pct: '+0.4%', up: true },
  { label: 'AMZN', price: '182.44', pct: '-0.3%', up: false },
  { label: 'META', price: '502.30', pct: '+1.8%', up: true },
];

const formatClock = (): string =>
  new Date().toLocaleTimeString('zh-CN', {
    hour12: false,
    timeZone: 'Asia/Shanghai',
  });

export function WelcomePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { toast } = useToast();
  const { quotes: marketQuotes } = useMarketQuotes();
  const {
    authIdentity,
    subscriptionEmail,
    theme,
    setTheme,
    setSubscriptionEmail,
    setAuthIdentity,
    setSessionId,
    setEntryMode,
  } = useStore();

  const [clock, setClock] = useState<string>(formatClock());
  const [email, setEmail] = useState(subscriptionEmail || '');
  const [otpCode, setOtpCode] = useState('');
  const [codeSentTo, setCodeSentTo] = useState('');
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [switchingAccount, setSwitchingAccount] = useState(false);

  const isDark = theme === 'dark';
  const supabaseReady = useMemo(() => isSupabaseAuthConfigured(), []);
  const isLoggedIn = Boolean(authIdentity?.userId);
  const sessionText = authIdentity?.email || 'GUEST-001';
  const redirectPath = resolveFallbackPath(new URLSearchParams(location.search).get('from'));

  useEffect(() => {
    const timer = window.setInterval(() => setClock(formatClock()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const tickerItems = useMemo(() => {
    const parsed = marketQuotes
      .filter((item) => typeof item.price === 'number')
      .map((item) => {
        const price = item.price ?? 0;
        const pct = item.changePct ?? 0;
        const sign = pct >= 0 ? '+' : '';
        return {
          label: item.label,
          price: price.toFixed(2),
          pct: `${sign}${pct.toFixed(2)}%`,
          up: pct >= 0,
        };
      });

    return parsed.length > 0 ? parsed : FALLBACK_TICKERS;
  }, [marketQuotes]);

  const handleAnonymousEnter = () => {
    markWelcomeGatePassed();
    setAuthIdentity(null);
    setEntryMode('anonymous');
    setSessionId(buildAnonymousSessionId());
    navigate(redirectPath);
  };

  const handleSendCode = async () => {
    const normalizedEmail = String(email || '').trim();
    if (!supabaseReady) {
      toast({
        type: 'error',
        title: '登录未配置',
        message: '请先设置 VITE_SUPABASE_URL 与 VITE_SUPABASE_PUBLISHABLE_KEY',
      });
      return;
    }
    if (!isValidEmail(normalizedEmail)) {
      toast({
        type: 'error',
        title: '邮箱格式不正确',
        message: '请输入有效的邮箱地址',
      });
      return;
    }

    const client = getSupabaseClient();
    if (!client) {
      toast({
        type: 'error',
        title: '初始化失败',
        message: 'Supabase 客户端不可用',
      });
      return;
    }

    setSending(true);
    try {
      const { error } = await client.auth.signInWithOtp({
        email: normalizedEmail,
        options: {
          shouldCreateUser: true,
        },
      });
      if (error) throw error;
      setSubscriptionEmail(normalizedEmail);
      setCodeSentTo(normalizedEmail);
      toast({
        type: 'success',
        title: '验证码已发送',
        message: '请在邮箱中查看验证码并完成登录',
      });
    } catch (error) {
      toast({
        type: 'error',
        title: '发送失败',
        message: error instanceof Error ? error.message : '验证码发送失败',
      });
    } finally {
      setSending(false);
    }
  };

  const handleVerifyCode = async () => {
    const normalizedEmail = String(codeSentTo || email || '').trim();
    const normalizedCode = String(otpCode || '').trim();

    if (!supabaseReady) {
      toast({
        type: 'error',
        title: '登录未配置',
        message: '请先设置 VITE_SUPABASE_URL 与 VITE_SUPABASE_PUBLISHABLE_KEY',
      });
      return;
    }
    if (!isValidEmail(normalizedEmail)) {
      toast({
        type: 'error',
        title: '邮箱格式不正确',
        message: '请输入有效的邮箱地址',
      });
      return;
    }
    if (!normalizedCode) {
      toast({
        type: 'error',
        title: '请输入验证码',
        message: '请填写邮箱收到的验证码',
      });
      return;
    }

    const client = getSupabaseClient();
    if (!client) {
      toast({
        type: 'error',
        title: '初始化失败',
        message: 'Supabase 客户端不可用',
      });
      return;
    }

    setVerifying(true);
    try {
      const { error } = await client.auth.verifyOtp({
        email: normalizedEmail,
        token: normalizedCode,
        type: 'email',
      });
      if (error) throw error;

      markWelcomeGatePassed();
      setSubscriptionEmail(normalizedEmail);
      toast({
        type: 'success',
        title: '登录成功',
        message: '验证通过，正在进入工作台',
      });
      navigate(redirectPath);
    } catch (error) {
      toast({
        type: 'error',
        title: '验证码无效',
        message: error instanceof Error ? error.message : '请检查验证码并重试',
      });
    } finally {
      setVerifying(false);
    }
  };

  const handleSwitchAccount = async () => {
    const client = getSupabaseClient();
    setSwitchingAccount(true);
    try {
      if (client) {
        const { error } = await client.auth.signOut();
        if (error) throw error;
      }

      if (typeof window !== 'undefined') {
        window.sessionStorage.removeItem(WELCOME_GATE_KEY);
      }

      setAuthIdentity(null);
      setEntryMode('pending');
      setSessionId(buildAnonymousSessionId());
      setSubscriptionEmail('');
      setEmail('');
      setCodeSentTo('');
      setOtpCode('');

      toast({
        type: 'success',
        title: '已退出当前账号',
        message: '请输入新的邮箱验证码登录',
      });
    } catch (error) {
      toast({
        type: 'error',
        title: '切换失败',
        message: error instanceof Error ? error.message : '账号切换失败，请重试',
      });
    } finally {
      setSwitchingAccount(false);
    }
  };

  const paletteVars = isDark
    ? {
        '--bb-bg': '#0a0e17',
        '--bb-surface': '#111827',
        '--bb-surface-2': '#1a2036',
        '--bb-border': '#1e2a3a',
        '--bb-text': '#e2e8f0',
        '--bb-text-dim': '#64748b',
        '--bb-orange': '#ff8c00',
        '--bb-orange-dim': 'rgba(255, 140, 0, 0.15)',
        '--bb-green': '#00e676',
        '--bb-red': '#ff5252',
        '--bb-blue': '#2979ff',
      }
    : {
        '--bb-bg': '#f7fafc',
        '--bb-surface': '#ffffff',
        '--bb-surface-2': '#edf2f7',
        '--bb-border': '#dbe4ef',
        '--bb-text': '#0f172a',
        '--bb-text-dim': '#475569',
        '--bb-orange': '#ff7a00',
        '--bb-orange-dim': 'rgba(255, 122, 0, 0.12)',
        '--bb-green': '#059669',
        '--bb-red': '#dc2626',
        '--bb-blue': '#2563eb',
      };

  return (
    <main className="relative h-screen overflow-y-auto font-mono" style={paletteVars as React.CSSProperties}>
      <div className="fixed inset-0 bg-[var(--bb-bg)]" />
      <div className="fixed inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(255,140,0,0.14),transparent_35%),radial-gradient(circle_at_80%_0%,rgba(41,121,255,0.10),transparent_30%)]" />

      <div className="relative z-20 h-9 border-b border-[var(--bb-border)] bg-[var(--bb-surface)] px-4 text-[11px] text-[var(--bb-text-dim)] flex items-center justify-between max-[480px]:px-2 max-[480px]:gap-2">
        <div className="flex items-center gap-6 max-[480px]:gap-2 min-w-0">
          <span className="tracking-wide shrink-0">FINSIGHT</span>
          <span className="max-[480px]:hidden">
            SESSION: <span className="text-[var(--bb-text)]">{sessionText}</span>
          </span>
          <span className="max-[640px]:hidden">
            MARKET: <span className="text-[var(--bb-green)]">OPEN</span>
          </span>
        </div>
        <div className="shrink-0">
          <span className="font-semibold text-[var(--bb-orange)]">{clock}</span>
          <span className="ml-2 max-[480px]:hidden">UTC+8</span>
        </div>
      </div>

      <section className="relative z-20 mx-auto grid min-h-[calc(100vh-68px)] w-full max-w-[1180px] grid-cols-[minmax(0,680px)_380px] items-center justify-center gap-8 px-6 py-6 max-[960px]:grid-cols-1 max-[960px]:px-5 max-[960px]:py-8 max-[480px]:gap-5 max-[480px]:px-4 max-[480px]:py-5 max-[480px]:min-h-0">
        <div className="flex flex-col gap-8 max-[480px]:gap-5">
          <div className="flex items-center gap-3 max-[480px]:gap-2">
            <img src="/logo.svg" alt="FinSight AI" className="h-12 w-12 max-[480px]:h-9 max-[480px]:w-9 rounded-[10px] shadow-[0_0_30px_rgba(255,140,0,0.3)]" />
            <div className="text-[32px] max-[480px]:text-[24px] leading-none font-bold text-[var(--bb-text)]">
              Fin<span className="text-[var(--bb-orange)]">Sight</span> AI
            </div>
            <span className="ml-1 rounded border border-[var(--bb-orange)] px-2 py-0.5 text-[10px] tracking-wide text-[var(--bb-orange)] max-[480px]:hidden">
              PRO TERMINAL
            </span>
          </div>

          <h1 className="max-w-[720px] text-[42px] leading-[1.2] font-bold text-[var(--bb-text)] max-[960px]:text-[32px] max-[480px]:text-[24px]">
            面向实盘研究的
            <span className="block text-[var(--bb-orange)]">AI 投研工作台</span>
          </h1>

          <p className="max-w-[700px] text-base leading-8 text-[var(--bb-text-dim)] max-[480px]:text-sm max-[480px]:leading-7">
            7 个研究智能体并行执行 · LangGraph 18 节点管线 · 6 个专业仪表盘标签页
            <br />
            混合 RAG 检索 · 跨智能体冲突检测 · 实时邮件预警
          </p>

          <div className="grid grid-cols-3 gap-3 max-[960px]:grid-cols-2 max-[480px]:grid-cols-3 max-[480px]:gap-2">
            {METRIC_CARDS.map((item) => (
              <div
                key={item.label}
                className="rounded-lg border border-[var(--bb-border)] bg-[var(--bb-surface)] p-4 max-[480px]:p-3 transition-colors hover:border-[var(--bb-orange)]"
              >
                <div className="mb-2 text-[10px] uppercase tracking-widest text-[var(--bb-text-dim)]">{item.label}</div>
                <div className="text-[32px] max-[480px]:text-[24px] leading-none font-semibold text-[var(--bb-text)]">{item.value}</div>
                <div className="mt-2 text-[11px] text-[var(--bb-green)]">{item.change}</div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-2 max-[480px]:hidden">
            {CAPABILITIES.map((item) => (
              <span
                key={item}
                className="rounded-md border border-[var(--bb-border)] bg-[var(--bb-surface)] px-3 py-1.5 text-[11px] text-[var(--bb-text-dim)] transition-all hover:border-[var(--bb-orange)] hover:bg-[var(--bb-orange-dim)] hover:text-[var(--bb-orange)]"
              >
                {item}
              </span>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-[var(--bb-border)] bg-[var(--bb-surface)] p-8 max-[480px]:p-5 shadow-xl relative overflow-hidden h-fit">
          <div className="absolute left-0 right-0 top-0 h-[3px] bg-[linear-gradient(90deg,var(--bb-orange),var(--bb-blue),var(--bb-green))]" />

          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-2xl font-semibold text-[var(--bb-text)]">接入工作台</h2>
              <p className="mt-1 text-sm text-[var(--bb-text-dim)]">统一使用邮箱验证码登录/注册</p>
            </div>
            <button
              type="button"
              onClick={() => setTheme(isDark ? 'light' : 'dark')}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--bb-border)] bg-[var(--bb-surface-2)] px-2.5 py-1 text-[11px] text-[var(--bb-text-dim)] transition-colors hover:border-[var(--bb-orange)] hover:text-[var(--bb-orange)]"
              title="切换背景"
            >
              {isDark ? <Sun size={12} /> : <Moon size={12} />}
              {isDark ? '白底' : '黑底'}
            </button>
          </div>

          {isLoggedIn ? (
            <div className="mt-7 space-y-4">
              <div className="rounded-lg border border-[var(--bb-border)] bg-[var(--bb-surface-2)] px-4 py-3 text-sm text-[var(--bb-text-dim)]">
                当前账号：<span className="font-medium text-[var(--bb-text)]">{authIdentity?.email || '已验证用户'}</span>
              </div>
              <Button
                variant="primary"
                size="lg"
                onClick={() => {
                  markWelcomeGatePassed();
                  navigate(redirectPath);
                }}
                className="w-full !bg-[linear-gradient(135deg,var(--bb-orange),#ff6d00)] !text-black font-semibold"
              >
                继续进入
              </Button>
              <button
                type="button"
                onClick={handleSwitchAccount}
                disabled={switchingAccount}
                className="mx-auto block text-xs text-[var(--bb-text-dim)] hover:text-[var(--bb-orange)] disabled:opacity-60"
              >
                {switchingAccount ? '切换中...' : '切换邮箱'}
              </button>
            </div>
          ) : (
            <div className="mt-7 space-y-4">
              <Input
                label="邮箱"
                type="email"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setSubscriptionEmail(event.target.value);
                }}
                placeholder="trader@example.com"
                autoComplete="email"
                className="py-2.5 !bg-[var(--bb-bg)] !border-[var(--bb-border)] !text-[var(--bb-text)]"
              />
              <Button
                variant="primary"
                size="lg"
                onClick={handleSendCode}
                disabled={sending || !supabaseReady}
                className="w-full !bg-[linear-gradient(135deg,var(--bb-orange),#ff6d00)] !text-black font-semibold"
              >
                <Mail size={14} />
                {sending ? '发送中...' : '发送验证码'}
              </Button>
              <Input
                label={`验证码${codeSentTo ? `（已发送至 ${codeSentTo}）` : ''}`}
                type="text"
                value={otpCode}
                onChange={(event) => setOtpCode(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && otpCode.trim() && !verifying) {
                    void handleVerifyCode();
                  }
                }}
                placeholder="输入邮箱收到的验证码"
                autoComplete="one-time-code"
                className="py-2.5 !bg-[var(--bb-bg)] !border-[var(--bb-border)] !text-[var(--bb-text)]"
              />
              <Button
                variant="secondary"
                size="lg"
                onClick={handleVerifyCode}
                disabled={verifying || !supabaseReady || !otpCode.trim()}
                className="w-full !border-[var(--bb-border)] !bg-transparent !text-[var(--bb-text)] hover:!bg-[var(--bb-surface-2)]"
              >
                <Mail size={14} />
                {verifying ? '验证中...' : '验证并登录'}
              </Button>

              <div className="my-4 flex items-center gap-3 text-xs text-[var(--bb-text-dim)]">
                <div className="h-px flex-1 bg-[var(--bb-border)]" />
                或
                <div className="h-px flex-1 bg-[var(--bb-border)]" />
              </div>

              <Button
                variant="secondary"
                size="lg"
                onClick={handleAnonymousEnter}
                className="w-full !border-[var(--bb-border)] !bg-transparent !text-[var(--bb-text)] hover:!bg-[var(--bb-surface-2)]"
              >
                匿名体验（数据仅存本地）
              </Button>

              <div className="mt-2 rounded-lg border border-[rgba(255,140,0,0.25)] bg-[var(--bb-orange-dim)] px-3 py-2 text-xs text-[var(--bb-text-dim)] flex items-start gap-2 leading-6">
                <CircleAlert size={14} className="mt-1 shrink-0 text-[var(--bb-orange)]" />
                <span>邮箱验证码登录支持跨设备持久化会话；匿名体验更快，但清理缓存后数据可能丢失。</span>
              </div>
            </div>
          )}

          <p className="mt-6 text-center text-[11px] leading-5 text-[var(--bb-text-dim)] opacity-70">
            FinSight AI v2.0 · 基于 LangGraph 构建
          </p>
        </div>
      </section>

      <div className="relative z-20 h-8 border-t border-[var(--bb-border)] bg-[var(--bb-surface)] overflow-hidden flex items-center">
        <div className="flex w-max items-center gap-10 px-4 text-[11px] text-[var(--bb-text-dim)]" style={{ animation: 'finsight-marquee 30s linear infinite' }}>
          {[...tickerItems, ...tickerItems].map((item, index) => (
            <span key={`${item.label}-${index}`} className="whitespace-nowrap">
              {item.label}{' '}
              <span className={item.up ? 'text-[var(--bb-green)]' : 'text-[var(--bb-red)]'}>
                {item.price} {item.pct}
              </span>
            </span>
          ))}
        </div>
      </div>
    </main>
  );
}

import { useEffect, useMemo, useState } from 'react';
import { CircleAlert, Mail, Moon, Sun } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  getRagInspectorDevIdentity,
  isRagInspectorDevAuthAvailable,
  setRagInspectorDevAuthActive,
  verifyRagInspectorDevAccessPassword,
} from '../../auth/devAuth';
import { buildRagInspectorAccessDiagnostics } from '../../auth/ragInspectorAccess';
import { getSupabaseClient, isSupabaseAuthConfigured } from '../../api/supabaseClient';
import { useMarketQuotes } from '../../hooks/useMarketQuotes';
import { buildAnonymousSessionId, buildUserSessionId, useStore } from '../../store/useStore';
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

const isAuthenticatedOnlyPath = (path: string): boolean => path === '/rag-inspector' || path.startsWith('/rag-inspector?');

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

// Aurora 配色语义：数据卡彩色顶边 + 数字色
const METRIC_CARDS = [
  { label: '智能体数', value: '7', change: '并行执行', accent: 'var(--bb-orange)' },
  { label: '仪表盘', value: '6', change: '分析标签页', accent: 'var(--bb-purple)' },
  { label: '冲突检测', value: '8', change: '智能体维度对', accent: 'var(--bb-green)' },
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
  const [ragInspectorPassword, setRagInspectorPassword] = useState('');

  const isDark = theme === 'dark';
  const supabaseReady = useMemo(() => isSupabaseAuthConfigured(), []);
  const isLoggedIn = Boolean(authIdentity?.userId);
  const sessionText = authIdentity?.email || 'GUEST-001';
  const redirectPath = resolveFallbackPath(new URLSearchParams(location.search).get('from'));
  const requiresAuthenticatedEntry = isAuthenticatedOnlyPath(redirectPath);
  const devAuthReady = useMemo(() => isRagInspectorDevAuthAvailable(), []);
  const ragAccessDiagnostics = useMemo(
    () => buildRagInspectorAccessDiagnostics({
      requiresAuthenticatedEntry,
      supabaseReady,
      devAuthReady,
    }),
    [requiresAuthenticatedEntry, supabaseReady, devAuthReady],
  );

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
    if (requiresAuthenticatedEntry) {
      toast({
        type: 'error',
        title: '该页面需要登录',
        message: devAuthReady
          ? 'RAG Inspector 只允许登录态访问；本地联调请点击“开发模式进入 RAG Inspector”。'
          : 'RAG Inspector 只允许登录态访问，匿名体验会被路由守卫直接拦回欢迎页。',
      });
      return;
    }

    markWelcomeGatePassed();
    setAuthIdentity(null);
    setEntryMode('anonymous');
    setSessionId(buildAnonymousSessionId());
    navigate(redirectPath);
  };

  const handleDevAuthEnter = () => {
    const devIdentity = getRagInspectorDevIdentity();
    if (!devIdentity) {
      toast({
        type: 'error',
        title: '开发模式未配置',
        message: '请先设置 VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN。',
      });
      return;
    }

    setRagInspectorDevAuthActive(true);
    markWelcomeGatePassed();
    setAuthIdentity(devIdentity);
    setEntryMode('authenticated');
    setSessionId(buildUserSessionId(devIdentity.userId));
    if (devIdentity.email) {
      setSubscriptionEmail(devIdentity.email);
      setEmail(devIdentity.email);
    }

    toast({
      type: 'success',
      title: '开发模式已启用',
      message: '已注入本地测试身份，正在进入 RAG Inspector。',
    });
    navigate(redirectPath);
  };

  const handleDevPasswordEnter = () => {
    const normalizedPassword = String(ragInspectorPassword || '').trim();
    if (!devAuthReady) {
      toast({
        type: 'error',
        title: '开发模式未配置',
        message: '请先设置 VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN。',
      });
      return;
    }
    if (!normalizedPassword) {
      toast({
        type: 'error',
        title: '请输入密码',
        message: '请输入 RAG Inspector 本地访问密码。',
      });
      return;
    }
    if (!verifyRagInspectorDevAccessPassword(normalizedPassword)) {
      toast({
        type: 'error',
        title: '密码错误',
        message: '本地访问密码不正确，请重试。',
      });
      return;
    }
    setRagInspectorPassword('');
    handleDevAuthEnter();
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

      setRagInspectorDevAuthActive(false);

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

  // ─────────────────────────────────────────────
  // Aurora 调色板（自包含亮暗，不依赖全局 .dark class）
  // 亮：白底靛蓝多彩；暗：深底亮靛蓝镜像
  // ─────────────────────────────────────────────
  const paletteVars = isDark
    ? {
        '--bb-bg': '#070a14',
        '--bb-surface': '#101627',
        '--bb-surface-2': '#192034',
        '--bb-border': 'rgba(107,138,255,0.16)',
        '--bb-border-2': 'rgba(107,138,255,0.28)',
        '--bb-text': '#e9edfb',
        '--bb-text-dim': '#9aa3c4',
        '--bb-text-mute': '#69718f',
        '--bb-orange': '#6b8aff',
        '--bb-orange-dim': 'rgba(107,138,255,0.14)',
        '--bb-blue': '#748ffc',
        '--bb-green': '#2bd576',
        '--bb-red': '#ff6b6b',
        '--bb-amber': '#ffa94d',
        '--bb-purple': '#9775fa',
        '--bb-teal': '#3bc9db',
        '--bb-aurora':
          'radial-gradient(ellipse 52% 56% at 14% 16%, rgba(107,138,255,0.20), transparent 62%), radial-gradient(ellipse 46% 50% at 88% 8%, rgba(151,117,250,0.15), transparent 60%), radial-gradient(ellipse 42% 48% at 92% 88%, rgba(59,201,219,0.12), transparent 62%), radial-gradient(ellipse 48% 42% at 42% 98%, rgba(43,213,118,0.09), transparent 60%)',
        '--bb-card-shadow': '0 1px 2px rgba(0,0,0,.4), 0 16px 48px -16px rgba(0,0,0,.6)',
        '--bb-soft-shadow': '0 1px 2px rgba(0,0,0,.3), 0 10px 30px -16px rgba(0,0,0,.5)',
      }
    : {
        '--bb-bg': '#eef1f8',
        '--bb-surface': '#ffffff',
        '--bb-surface-2': '#f4f6fc',
        '--bb-border': 'rgba(59,91,219,0.12)',
        '--bb-border-2': 'rgba(59,91,219,0.22)',
        '--bb-text': '#0f1b4d',
        '--bb-text-dim': '#5a6482',
        '--bb-text-mute': '#8b93b0',
        '--bb-orange': '#3b5bdb',
        '--bb-orange-dim': 'rgba(59,91,219,0.10)',
        '--bb-blue': '#4c6ef5',
        '--bb-green': '#15a05a',
        '--bb-red': '#e03131',
        '--bb-amber': '#ec8413',
        '--bb-purple': '#7048e8',
        '--bb-teal': '#0c8599',
        '--bb-aurora':
          'radial-gradient(ellipse 52% 56% at 14% 16%, rgba(59,91,219,0.12), transparent 62%), radial-gradient(ellipse 46% 50% at 88% 8%, rgba(112,72,232,0.09), transparent 60%), radial-gradient(ellipse 42% 48% at 92% 88%, rgba(12,133,153,0.08), transparent 62%), radial-gradient(ellipse 48% 42% at 42% 98%, rgba(21,160,90,0.06), transparent 60%)',
        '--bb-card-shadow': '0 1px 2px rgba(15,27,77,.05), 0 4px 12px rgba(59,91,219,.06), 0 24px 48px -20px rgba(59,91,219,.28)',
        '--bb-soft-shadow': '0 1px 2px rgba(15,27,77,.04), 0 8px 24px -14px rgba(59,91,219,.20)',
      };

  return (
    <main className="relative h-screen overflow-y-auto" style={paletteVars as React.CSSProperties}>
      <div className="fixed inset-0 bg-[var(--bb-bg)]" />
      <div className="fixed inset-0" style={{ background: 'var(--bb-aurora)' }} />

      <div className="relative z-20 h-9 border-b border-[var(--bb-border)] bg-[var(--bb-surface)] px-4 text-[11px] font-mono text-[var(--bb-text-mute)] flex items-center justify-between max-[480px]:px-2 max-[480px]:gap-2">
        <div className="flex items-center gap-6 max-[480px]:gap-2 min-w-0">
          <span className="tracking-[0.12em] font-semibold text-[var(--bb-orange)] shrink-0">FINSIGHT</span>
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

      <section className="relative z-20 mx-auto grid min-h-[calc(100vh-68px)] w-full max-w-[1200px] grid-cols-[minmax(0,1fr)_412px] items-center justify-center gap-14 px-10 py-7 max-[960px]:grid-cols-1 max-[960px]:px-5 max-[960px]:py-8 max-[480px]:gap-5 max-[480px]:px-4 max-[480px]:py-5 max-[480px]:min-h-0">
        <div className="flex flex-col gap-7 max-[480px]:gap-5">
          <div className="flex items-center gap-3 max-[480px]:gap-2">
            <div className="grid h-[50px] w-[50px] max-[480px]:h-9 max-[480px]:w-9 place-items-center rounded-[13px] border border-[var(--bb-border)] bg-[var(--bb-surface)] shadow-[var(--bb-soft-shadow)]">
              <svg width="30" height="30" viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg">
                <line x1="30" y1="8" x2="30" y2="36" stroke="var(--bb-amber)" strokeWidth="1.6" strokeLinecap="round" />
                <rect x="26" y="14" width="8" height="14" rx="2" fill="var(--bb-amber)" />
                <line x1="16" y1="6" x2="16" y2="38" stroke="var(--bb-orange)" strokeWidth="1.6" strokeLinecap="round" />
                <rect x="12" y="12" width="8" height="16" rx="2" fill="var(--bb-orange)" />
                <rect x="12" y="24" width="20" height="2.6" rx="1.3" fill="var(--bb-orange)" opacity="0.25" />
              </svg>
            </div>
            <div className="text-[30px] max-[480px]:text-[24px] leading-none font-bold tracking-tight text-[var(--bb-text)]">
              Fin<span className="text-[var(--bb-orange)]">Sight</span> AI
            </div>
            <span className="ml-1 rounded-md border border-[var(--bb-border-2)] px-2 py-0.5 text-[10px] font-mono tracking-[0.14em] text-[var(--bb-orange)] max-[480px]:hidden">
              PRO TERMINAL
            </span>
          </div>

          <h1 className="max-w-[720px] text-[46px] leading-[1.12] font-extrabold tracking-tight text-[var(--bb-text)] max-[960px]:text-[34px] max-[480px]:text-[26px]">
            面向实盘研究的
            <span className="block text-[var(--bb-orange)]">AI 投研工作台</span>
          </h1>

          <p className="max-w-[640px] text-[15px] leading-[1.85] text-[var(--bb-text-dim)] max-[480px]:text-sm max-[480px]:leading-7">
            7 个研究智能体并行执行 · 有状态 LangGraph 编排 · 6 个专业仪表盘标签页
            <br />
            混合 RAG 检索 · 跨智能体冲突检测 · 实时邮件预警
          </p>

          <div className="grid grid-cols-3 gap-3.5 max-[960px]:grid-cols-3 max-[480px]:gap-2">
            {METRIC_CARDS.map((item) => (
              <div
                key={item.label}
                className="relative overflow-hidden rounded-[14px] border border-[var(--bb-border)] bg-[var(--bb-surface)] p-4 max-[480px]:p-3 shadow-[var(--bb-soft-shadow)] transition-transform duration-200 hover:-translate-y-[3px]"
              >
                <div className="absolute left-0 right-0 top-0 h-[2px]" style={{ background: item.accent }} />
                <div className="mb-2 text-[9.5px] font-mono uppercase tracking-[0.12em] text-[var(--bb-text-mute)]">{item.label}</div>
                <div className="text-[34px] max-[480px]:text-[26px] font-mono font-semibold leading-none" style={{ color: item.accent }}>{item.value}</div>
                <div className="mt-2 text-[11px] text-[var(--bb-text-dim)]">{item.change}</div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-2 max-[480px]:hidden">
            {CAPABILITIES.map((item) => (
              <span
                key={item}
                className="rounded-lg border border-[var(--bb-border)] bg-[var(--bb-surface)] px-3 py-1.5 text-[12px] text-[var(--bb-text-dim)] transition-all hover:border-[var(--bb-orange)] hover:bg-[var(--bb-orange-dim)] hover:text-[var(--bb-orange)]"
              >
                {item}
              </span>
            ))}
          </div>

          <svg className="max-w-[600px] opacity-90 max-[480px]:hidden" width="100%" height="40" viewBox="0 0 580 40" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
            <polyline points="0,30 48,27 96,28 144,22 192,24 240,17 288,19 336,12 384,14 432,8 480,11 528,6 580,9" fill="none" stroke="var(--bb-orange)" strokeWidth="1.5" opacity="0.32" />
            <g opacity="0.7">
              <line x1="144" y1="18" x2="144" y2="28" stroke="var(--bb-green)" strokeWidth="1.5" /><rect x="138" y="20" width="12" height="8" rx="1.5" fill="var(--bb-green)" />
              <line x1="288" y1="14" x2="288" y2="24" stroke="var(--bb-red)" strokeWidth="1.5" /><rect x="282" y="16" width="12" height="8" rx="1.5" fill="var(--bb-red)" />
              <line x1="432" y1="4" x2="432" y2="14" stroke="var(--bb-green)" strokeWidth="1.5" /><rect x="426" y="6" width="12" height="8" rx="1.5" fill="var(--bb-green)" />
              <line x1="528" y1="2" x2="528" y2="12" stroke="var(--bb-green)" strokeWidth="1.5" /><rect x="522" y="4" width="12" height="8" rx="1.5" fill="var(--bb-green)" />
            </g>
          </svg>
        </div>

        <div className="rounded-[20px] border border-[var(--bb-border)] bg-[var(--bb-surface)] p-[30px] max-[480px]:p-5 shadow-[var(--bb-card-shadow)] relative overflow-hidden h-fit">
          <div className="absolute left-0 right-0 top-0 h-[3px] bg-[linear-gradient(90deg,var(--bb-orange),var(--bb-purple),var(--bb-teal),var(--bb-green))]" />

          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-2xl font-bold tracking-tight text-[var(--bb-text)]">接入工作台</h2>
              <p className="mt-1.5 text-sm text-[var(--bb-text-dim)]">匿名本地会话最快；需要跨设备时再登录</p>
            </div>
            <button
              type="button"
              onClick={() => setTheme(isDark ? 'light' : 'dark')}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--bb-border)] bg-[var(--bb-surface-2)] px-2.5 py-1.5 text-[11px] font-mono text-[var(--bb-text-dim)] transition-colors hover:border-[var(--bb-orange)] hover:text-[var(--bb-orange)]"
              title="切换亮暗主题"
            >
              {isDark ? <Sun size={12} /> : <Moon size={12} />}
              {isDark ? '白底' : '黑底'}
            </button>
          </div>

          {isLoggedIn ? (
            <div className="mt-6 space-y-4">
              <div className="rounded-xl border border-[var(--bb-border)] bg-[var(--bb-surface-2)] px-4 py-3 text-sm text-[var(--bb-text-dim)]">
                当前账号：<span className="font-medium text-[var(--bb-text)]">{authIdentity?.email || '已验证用户'}</span>
              </div>
              <Button
                variant="primary"
                size="lg"
                onClick={() => {
                  markWelcomeGatePassed();
                  navigate(redirectPath);
                }}
                className="w-full !rounded-[11px] !bg-[linear-gradient(135deg,var(--bb-orange),var(--bb-blue))] !text-white font-semibold !shadow-[0_8px_20px_-8px_var(--bb-orange)]"
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
            <div className="mt-6 space-y-3.5">
              {!requiresAuthenticatedEntry ? (
                <>
                  <Button
                    variant="primary"
                    size="lg"
                    onClick={handleAnonymousEnter}
                    className="w-full !rounded-[11px] !bg-[linear-gradient(135deg,var(--bb-orange),var(--bb-blue))] !text-white font-semibold !shadow-[0_8px_20px_-8px_var(--bb-orange)]"
                  >
                    匿名体验（本地会话）
                  </Button>

                  <div className="my-3 flex items-center gap-3 text-xs text-[var(--bb-text-mute)]">
                    <div className="h-px flex-1 bg-[var(--bb-border)]" />
                    或用邮箱登录
                    <div className="h-px flex-1 bg-[var(--bb-border)]" />
                  </div>
                </>
              ) : null}

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
                className="py-2.5 font-mono !rounded-[10px] !bg-[var(--bb-surface-2)] !border-[var(--bb-border)] !text-[var(--bb-text)] focus:!border-[var(--bb-orange)]"
              />
              <Button
                variant="primary"
                size="lg"
                onClick={handleSendCode}
                disabled={sending || !supabaseReady}
                className="w-full !rounded-[11px] !bg-[linear-gradient(135deg,var(--bb-orange),var(--bb-blue))] !text-white font-semibold !shadow-[0_8px_20px_-8px_var(--bb-orange)]"
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
                className="py-2.5 font-mono !rounded-[10px] !bg-[var(--bb-surface-2)] !border-[var(--bb-border)] !text-[var(--bb-text)] focus:!border-[var(--bb-orange)]"
              />
              <Button
                variant="secondary"
                size="lg"
                onClick={handleVerifyCode}
                disabled={verifying || !supabaseReady || !otpCode.trim()}
                className="w-full !rounded-[11px] !border-[var(--bb-border-2)] !bg-transparent !text-[var(--bb-text)] hover:!bg-[var(--bb-surface-2)] hover:!border-[var(--bb-orange)]"
              >
                <Mail size={14} />
                {verifying ? '验证中...' : '验证并登录'}
              </Button>

              {requiresAuthenticatedEntry && devAuthReady ? (
                <div className="mt-3 space-y-3 rounded-xl border border-[var(--bb-border-2)] bg-[var(--bb-orange-dim)] px-3 py-3">
                  <Input
                    label={'RAG Inspector 密码'}
                    type="password"
                    value={ragInspectorPassword}
                    onChange={(event) => setRagInspectorPassword(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        handleDevPasswordEnter();
                      }
                    }}
                    placeholder={'输入本地访问密码'}
                    autoComplete="current-password"
                    className="py-2.5 font-mono !rounded-[10px] !bg-[var(--bb-surface-2)] !border-[var(--bb-border-2)] !text-[var(--bb-text)]"
                  />
                  <Button
                    variant="secondary"
                    size="lg"
                    onClick={handleDevPasswordEnter}
                    className="w-full !rounded-[11px] !border-[var(--bb-border-2)] !bg-[var(--bb-orange-dim)] !text-[var(--bb-text)] hover:!bg-[var(--bb-surface-2)]"
                  >
                    {'输入密码进入 RAG Inspector'}
                  </Button>
                  <div className="text-[11px] leading-5 text-[var(--bb-text-dim)]">
                    {'这是本地开发门禁，主要用于联调入口收口；真正的数据读取权限仍由后端鉴权决定。'}
                  </div>
                </div>
              ) : null}

              {requiresAuthenticatedEntry ? (
                <div className="mt-3 rounded-xl border border-[var(--bb-border-2)] bg-[var(--bb-orange-dim)] px-3 py-3 text-xs text-[var(--bb-text-dim)] leading-6">
                  <div className="flex items-start gap-2">
                    <CircleAlert size={14} className="mt-1 shrink-0 text-[var(--bb-orange)]" />
                    <div className="min-w-0">
                      <div className="font-semibold text-[var(--bb-text)]">{ragAccessDiagnostics.title}</div>
                      <ul className="mt-1 space-y-1">
                        {ragAccessDiagnostics.reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                      {ragAccessDiagnostics.nextSteps.length > 0 ? (
                        <div className="mt-2 text-[var(--bb-orange)]">
                          {ragAccessDiagnostics.nextSteps.join(' ')}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              ) : null}

              <div className="mt-2 rounded-xl border border-[var(--bb-border-2)] bg-[var(--bb-orange-dim)] px-3 py-2.5 text-xs text-[var(--bb-text-dim)] flex items-start gap-2 leading-6">
                <CircleAlert size={14} className="mt-1 shrink-0 text-[var(--bb-orange)]" />
                <span>邮箱验证码登录支持跨设备持久化会话；匿名体验更快，但清理缓存后数据可能丢失。</span>
              </div>
            </div>
          )}

          <p className="mt-6 text-center text-[11px] font-mono leading-5 text-[var(--bb-text-mute)] opacity-80">
            FinSight AI v2.0 · 基于 LangGraph 构建
          </p>
        </div>
      </section>

      <div className="relative z-20 h-8 border-t border-[var(--bb-border)] bg-[var(--bb-surface)] overflow-hidden flex items-center">
        <div className="flex w-max items-center gap-10 px-4 text-[11px] font-mono text-[var(--bb-text-dim)]" style={{ animation: 'finsight-marquee 30s linear infinite' }}>
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

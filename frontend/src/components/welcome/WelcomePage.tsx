import { ArrowRight, Mail, Moon, Sun, Github, Search, ChartNoAxesCombined, Code2, Check, Target } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { buildApiUrl } from '../../config/runtime';
import { apiClient } from '../../api/client';
import type { PredictionTrackRecord } from '../../types/predictions';

import { getSupabaseClient, isSupabaseAuthConfigured } from '../../api/supabaseClient';
import { buildAnonymousSessionId, buildUserSessionId, useStore } from '../../store/useStore';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { useToast } from '../ui';
import { safeLoginDestination } from './authOptions';

const WELCOME_GATE_KEY = 'finsight-welcome-gate-passed';

const markWelcomeGatePassed = (): void => {
  window.sessionStorage.setItem(WELCOME_GATE_KEY, '1');
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
  const [githubPending, setGithubPending] = useState(false);
  const oauthErrorShown = useRef(false);
  const [providers, setProviders] = useState<{ github: boolean; email: boolean; status: string } | null>(null);
  const [predictionProtocol, setPredictionProtocol] = useState<PredictionTrackRecord | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(buildApiUrl('/api/auth/providers'), { signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('provider_unavailable')))
      .then((value) => { if (!controller.signal.aborted) setProviders(value); })
      .catch(() => { if (!controller.signal.aborted) setProviders({ github: false, email: false, status: 'unavailable' }); });
    apiClient.getPredictionTrackRecord(1, 0, controller.signal).then(setPredictionProtocol).catch(() => {});
    return () => controller.abort();
  }, []);

  const destination = useMemo(
    () => safeLoginDestination(new URLSearchParams(location.search).get('from')),
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

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('auth_callback') !== 'github') return;
    if (params.has('error') || new URLSearchParams(location.hash.slice(1)).has('error')) {
      if (!oauthErrorShown.current) toast({ type: 'error', title: 'GitHub 登录未完成', message: '授权被取消，或者链接过期了，再试一次就好。' });
      oauthErrorShown.current = true;
      return;
    }
    if (!authIdentity?.userId) return;
    markWelcomeGatePassed();
    setEntryMode('authenticated');
    setSessionId(buildUserSessionId(authIdentity.userId));
    navigate(destination, { replace: true });
  }, [authIdentity?.userId, destination, location.search, location.hash, navigate, setEntryMode, setSessionId, toast]);

  const enterReadOnly = () => {
    markWelcomeGatePassed();
    setAuthIdentity(null);
    setEntryMode('anonymous');
    setSessionId(buildAnonymousSessionId());
    navigate(isAuthenticatedDestination(destination) ? '/dashboard/AAPL' : destination, { replace: true });
  };

  const signInWithGithub = async () => {
    const client = getSupabaseClient();
    if (!client || !providers?.github || providers.status !== 'ok') return;
    setGithubPending(true);
    try {
      const callback = new URL('/welcome', window.location.origin);
      callback.searchParams.set('from', destination);
      callback.searchParams.set('auth_callback', 'github');
      const { error } = await client.auth.signInWithOAuth({ provider: 'github', options: {
        redirectTo: callback.toString(), scopes: 'read:user user:email',
      } });
      if (error) throw error;
    } catch (error) {
      toast({ type: 'error', title: 'GitHub 登录未完成', message: error instanceof Error ? error.message : '登录没成功，稍后再试一次。' });
      setGithubPending(false);
    }
  };

  const sendCode = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (!/^\S+@\S+\.\S+$/.test(normalizedEmail)) {
      toast({ type: 'error', title: '请输入有效邮箱' });
      return;
    }
    const client = getSupabaseClient();
    if (!client) {
      toast({ type: 'error', title: '登录暂时不可用', message: '行情和战绩可以先看，稍后再试登录。' });
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
        message: error instanceof Error ? error.message : '验证码没发出去，稍后再试一次。',
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
      if (!userId) throw new Error('没有收到完整的登录信息，请重新登录。');
      enterAuthenticated(userId, data.user?.email || data.session?.user?.email || normalizedEmail);
    } catch (error) {
      toast({
        type: 'error',
        title: '验证码无效',
        message: error instanceof Error ? error.message : '请核对邮箱里的验证码，再试一次。',
      });
    } finally {
      setVerifying(false);
    }
  };

  const frequencyText = predictionProtocol?.metadata.frequency === 'trading_day'
    ? `每个交易日给 ${predictionProtocol.universe.tickers.length} 只美股下判断，到期自动对答案。${predictionProtocol.enabled ? '猜错的一条不删，还拿去和“永远猜涨”比。' : '自动预测暂停中，以前的记录照常可查。'}`
    : '更新节奏还没定，已经发布的预测照样会对答案。';

  return (
    <main className="welcome-page">
      <header className="welcome-header">
        <div className="welcome-brand"><img src="/logo.svg?v=8672cb27dc15" alt="" aria-hidden="true" /><span>FinSight</span></div>
        <nav className="welcome-nav" aria-label="公开页面"><Link to="/track-record">公开战绩</Link>
          <button type="button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} className="inline-flex size-8 items-center justify-center rounded-md hover:bg-t-hover" aria-label="切换主题">{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}</button>
        </nav>
      </header>
      <div className="welcome-stage"><div className="welcome-columns">
        <section className="welcome-intro" aria-label="投资研究助手">
          <div><h1 className="welcome-title">你只管问，<br /><span>剩下的交给 FinSight。</span></h1>
            <p className="welcome-description">它会自己查行情、翻财报、写代码算账、画图给你看。每个数字都标着出处，数据不够就直说。</p></div>
          <div className="welcome-demo" aria-label="研究过程示例">
            <div className="flex items-center justify-between gap-3"><span className="design-tag" style={{ color: 'var(--t-amber)', background: 'var(--t-amber-soft)' }}>示例</span><div className="welcome-demo-question">半导体 ETF 连跌 5 周，历史上像哪次？</div></div>
            <div>{[
              { Icon: Search, title: '拉取周线', text: 'SOXX 近 25 年', color: 'var(--t-amber)' },
              { Icon: Code2, title: '跑一段代码', text: '筛出所有连跌 ≥5 周的时段', color: 'var(--t-violet)' },
              { Icon: ChartNoAxesCombined, title: '画图', text: '把这几段叠在一起对比', color: 'var(--t-teal)' },
            ].map(({ Icon, title, text, color }) => <div className="welcome-demo-row" key={title}><Icon size={13} style={{ color }} /><span>{title}</span><span className="detail">{text}</span><Check size={12} className="text-t-text3" /></div>)}</div>
            <svg viewBox="0 0 560 90" width="100%" aria-hidden="true" className="rounded-lg" style={{ background: 'var(--t-bg-2)' }}><rect x="34" y="6" width="8" height="78" fill="var(--t-down)" fillOpacity=".12" /><rect x="148" y="6" width="6" height="78" fill="var(--t-down)" fillOpacity=".12" /><rect x="398" y="6" width="6" height="78" fill="var(--t-down)" fillOpacity=".12" /><polyline points="10,52 24,54 36,66 44,76 60,70 90,62 120,64 146,63 152,80 170,72 200,68 240,62 280,56 320,50 360,44 396,38 400,50 410,40 440,30 470,34 500,26 520,18 536,10 544,20" fill="none" stroke="rgb(var(--t-accent))" strokeWidth="1.8" strokeLinejoin="round" /></svg>
            <p className="text-[13.5px] text-t-text2">找到了几段相似的下跌。下一步看：那几次后来怎么走，这次又差在哪。</p>
          </div>
        </section>
        <section className="welcome-login" aria-label="登录">
          <div><h2>登录 FinSight</h2><p>登录后，对话、自选和研究记录都会帮你存好。</p></div>
          {authIdentity?.userId ? <><p className="truncate">{authIdentity.email || '已登录'}</p><Button className="welcome-button" onClick={() => enterAuthenticated(authIdentity.userId, authIdentity.email)}>继续使用 <ArrowRight size={15} /></Button></> : <>
            {providers?.status === 'ok' && providers.github && supabaseReady && <><button type="button" className="welcome-button github-button" onClick={() => void signInWithGithub()} disabled={githubPending}><Github size={18} />{githubPending ? '正在前往 GitHub…' : '使用 GitHub 登录'}</button>{providers.email && <div className="email-divider">或用邮箱</div>}</>}
            {providers?.status === 'ok' && providers.email && supabaseReady ? <form className="flex flex-col gap-2.5" onSubmit={(event) => { event.preventDefault(); void (codeSent ? verifyCode() : sendCode()); }}>
              <Input label="邮箱" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" autoComplete="email" />
              {!codeSent ? <Button type="submit" variant="secondary" className="welcome-button" disabled={sending}><Mail size={14} />{sending ? '发送中' : '发送验证码'}</Button> : <><Input label="验证码" value={otpCode} onChange={(event) => setOtpCode(event.target.value)} autoComplete="one-time-code" /><Button type="submit" className="welcome-button" disabled={verifying || !otpCode.trim()}>{verifying ? '验证中' : '验证并登录'}</Button><button type="button" className="text-xs text-t-text3" disabled={sending} onClick={() => void sendCode()}>重新发送验证码</button></>}
            </form> : !providers ? <p role="status">正在加载登录方式…</p> : !providers.github ? <p role="status">登录暂时出了点问题，行情和战绩可以先看。</p> : null}
          </>}
          <button type="button" className="flex min-h-10 items-center justify-center gap-1.5 rounded-[10px] text-[13.5px] text-t-text2 hover:bg-t-hover" onClick={enterReadOnly}>先逛逛，行情和战绩不用登录也能看 <ArrowRight size={14} /></button>
        </section>
      </div></div>
      <section className="welcome-features" aria-label="研究能力"><div className="welcome-feature-grid">
        {[{ Icon: Search, title: '要什么，查什么', text: '行情、财报、新闻、宏观数据都能查。每个数字都写明来自哪里、截至什么时候，是延迟数据也会标出来。', color: 'amber' },
          { Icon: Code2, title: '自己算，自己画', text: '“历史上像哪次？”“现在贵不贵？”它会写代码把账算清楚，再画成一眼能看懂的图。', color: 'violet' },
          { Icon: Target, title: '预测，敢对答案', text: frequencyText, color: 'teal' }].map(({ Icon, title, text, color }) => <div className="welcome-feature" key={title}><div className="icon" style={{ color: `var(--t-${color})`, background: `var(--t-${color}-soft)` }}><Icon size={18} /></div><h2>{title}</h2><p>{text}</p></div>)}
      </div></section>
    </main>
  );
}

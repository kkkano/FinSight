export interface RagInspectorAccessDiagnosticInput {
  requiresAuthenticatedEntry: boolean;
  supabaseReady: boolean;
  devAuthReady: boolean;
}

export interface RagInspectorAccessDiagnostics {
  title: string;
  reasons: string[];
  nextSteps: string[];
  canUseEmailLogin: boolean;
  canUseDevPassword: boolean;
}

export const buildRagInspectorAccessDiagnostics = ({
  requiresAuthenticatedEntry,
  supabaseReady,
  devAuthReady,
}: RagInspectorAccessDiagnosticInput): RagInspectorAccessDiagnostics => {
  if (!requiresAuthenticatedEntry) {
    return {
      title: '',
      reasons: [],
      nextSteps: [],
      canUseEmailLogin: supabaseReady,
      canUseDevPassword: devAuthReady,
    };
  }

  const reasons: string[] = ['RAG Inspector 默认只允许登录态访问，匿名体验不会放行。'];
  if (!supabaseReady) {
    reasons.push('缺少 VITE_SUPABASE_URL 或 VITE_SUPABASE_PUBLISHABLE_KEY，邮箱验证码登录不可用。');
  }
  if (!devAuthReady) {
    reasons.push('缺少 VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN，本地开发密码入口不可用。');
  }

  const nextSteps = supabaseReady || devAuthReady
    ? ['使用已配置的登录方式进入 RAG Inspector。']
    : ['配置 Supabase 邮箱登录，或为本地联调设置 VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN。'];

  return {
    title: 'RAG Inspector 需要登录配置',
    reasons,
    nextSteps,
    canUseEmailLogin: supabaseReady,
    canUseDevPassword: devAuthReady,
  };
};

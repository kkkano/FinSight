import { describe, expect, it } from 'vitest';

import { buildRagInspectorAccessDiagnostics } from './ragInspectorAccess';

describe('buildRagInspectorAccessDiagnostics', () => {
  it('explains when both Supabase auth and dev token are missing', () => {
    const diagnostics = buildRagInspectorAccessDiagnostics({
      requiresAuthenticatedEntry: true,
      supabaseReady: false,
      devAuthReady: false,
    });

    expect(diagnostics.canUseEmailLogin).toBe(false);
    expect(diagnostics.canUseDevPassword).toBe(false);
    expect(diagnostics.title).toBe('RAG Inspector 需要登录配置');
    expect(diagnostics.reasons).toContain('缺少 VITE_SUPABASE_URL 或 VITE_SUPABASE_PUBLISHABLE_KEY，邮箱验证码登录不可用。');
    expect(diagnostics.reasons).toContain('缺少 VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN，本地开发密码入口不可用。');
    expect(diagnostics.nextSteps).toContain('配置 Supabase 邮箱登录，或为本地联调设置 VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN。');
  });

  it('does not show diagnostics for normal anonymous entry paths', () => {
    const diagnostics = buildRagInspectorAccessDiagnostics({
      requiresAuthenticatedEntry: false,
      supabaseReady: false,
      devAuthReady: false,
    });

    expect(diagnostics.reasons).toEqual([]);
    expect(diagnostics.nextSteps).toEqual([]);
  });
});

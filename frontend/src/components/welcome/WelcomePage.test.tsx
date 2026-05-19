import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { ToastProvider } from '../ui';
import { WelcomePage } from './WelcomePage';

const renderWelcomeText = (path: string) =>
  renderToStaticMarkup(
    <MemoryRouter initialEntries={[path]}>
      <ToastProvider>
        <WelcomePage />
      </ToastProvider>
    </MemoryRouter>,
  ).replace(/\s+/g, ' ');

describe('WelcomePage', () => {
  it('keeps anonymous entry ahead of email login for normal workspace entry', () => {
    const text = renderWelcomeText('/welcome?from=/chat');

    expect(text.indexOf('匿名体验')).toBeGreaterThanOrEqual(0);
    expect(text.indexOf('邮箱')).toBeGreaterThanOrEqual(0);
    expect(text.indexOf('匿名体验')).toBeLessThan(text.indexOf('邮箱'));
  });

  it('explains missing RAG Inspector login configuration on guarded entry', () => {
    const text = renderWelcomeText('/welcome?from=/rag-inspector');

    expect(text).toContain('RAG Inspector 需要登录配置');
    expect(text).toContain('缺少 VITE_SUPABASE_URL 或 VITE_SUPABASE_PUBLISHABLE_KEY');
    expect(text).toContain('缺少 VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN');
  });
});

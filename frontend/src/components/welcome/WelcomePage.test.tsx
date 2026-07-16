import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { ToastProvider } from '../ui';
import { WelcomePage } from './WelcomePage';

vi.mock('../../api/supabaseClient', () => ({
  getSupabaseClient: () => null,
  isSupabaseAuthConfigured: () => false,
}));

const renderWelcomeText = (path: string) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <ToastProvider>
          <WelcomePage />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  ).replace(/\s+/g, ' ');
};

describe('WelcomePage', () => {
  it('uses the shared application skin', () => {
    const markup = renderWelcomeText('/welcome?from=/chat');

    expect(markup).not.toContain('--bb-');
    expect(markup).not.toContain('linear-gradient(135deg');
    expect(markup).toContain('bg-t-bg');
    expect(markup).toContain('text-t-accent');
  });

  it('offers authenticated login and read-only market access', () => {
    const text = renderWelcomeText('/welcome?from=/chat');

    expect(text.indexOf('浏览只读行情')).toBeGreaterThanOrEqual(0);
    expect(text.indexOf('邮箱')).toBeGreaterThanOrEqual(0);
    expect(text).toContain('发送验证码');
  });

  it('does not advertise removed product surfaces', () => {
    const text = renderWelcomeText('/welcome?from=/chat');

    expect(text).not.toContain('RAG Inspector');
    expect(text).not.toContain('邮件预警');
    expect(text).not.toContain('7 个研究智能体');
  });
});

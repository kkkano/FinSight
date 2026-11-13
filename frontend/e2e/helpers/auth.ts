import type { Page } from '@playwright/test';

export const E2E_USER_ID = 'e2e-user';
export const E2E_SESSION_ID = `public:${E2E_USER_ID}:default`;

export const installAuthenticatedSession = async (page: Page, options: { accessToken?: string } = {}) => {
  await page.route('**/src/api/supabaseClient.ts*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `
        const session = ${JSON.stringify({ user: { id: E2E_USER_ID, email: 'e2e@example.com' },
          ...(options.accessToken ? { access_token: options.accessToken } : {}) })};
        const client = {
          auth: {
            getSession: async () => ({ data: { session } }),
            onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
          },
        };
        export const isSupabaseAuthConfigured = () => true;
        export const getSupabaseClient = () => client;
      `,
    });
  });
};

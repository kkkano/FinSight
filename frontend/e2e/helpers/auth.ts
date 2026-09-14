import type { Page } from '@playwright/test';

export const E2E_USER_ID = 'e2e-user';
export const E2E_SESSION_ID = `public:${E2E_USER_ID}:default`;

export const installAuthenticatedSession = async (page: Page) => {
  await page.route('**/src/api/supabaseClient.ts*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: `
        const session = { user: { id: '${E2E_USER_ID}', email: 'e2e@example.com' } };
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

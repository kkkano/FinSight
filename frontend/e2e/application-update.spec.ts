import { expect, test } from '@playwright/test';

test('新版本提示不打断生成，也不让刷新丢失尚未发送的输入', async ({ page }) => {
  test.skip(!process.env.FRONTEND_BUILD_ID || process.env.FRONTEND_BUILD_ID === 'local', '需要构建版本 fixture');
  await page.addInitScript(() => sessionStorage.setItem('finsight-welcome-gate-passed', '1'));
  await page.route('**/src/api/supabaseClient.ts*', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: 'export const getSupabaseClient = () => null; export const isSupabaseAuthConfigured = () => false;',
  }));
  let versionRequests = 0;
  await page.route('**/app-version.json', (route) => {
    versionRequests += 1;
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ build_id: 'new-release-fixture' }) });
  });
  await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"healthy"}' }));
  await page.route('**/api/**', (route) => {
    if (!new URL(route.request().url()).pathname.startsWith('/api/')) return route.fallback();
    return route.fulfill({ contentType: 'application/json', body: '{"data":{},"items":[],"models":[],"success":true}' });
  });
  await page.goto('/today');
  const refresh = page.getByRole('button', { name: '刷新更新' });
  await expect(refresh).toBeVisible();
  await expect(refresh).toBeEnabled();
  expect(versionRequests).toBeGreaterThan(0);
  await page.evaluate(async () => {
    const path = '/src/store/useStore.ts';
    const { useStore } = await import(path);
    useStore.getState().setLoading(true);
  });
  await expect(refresh).toBeDisabled();
  await expect(page.getByText('新版本已就绪，本次回答结束后即可更新。')).toBeVisible();
  await page.evaluate(async () => {
    const path = '/src/store/useStore.ts';
    const { useStore } = await import(path);
    useStore.getState().setLoading(false);
    useStore.getState().setDraft('尚未发送的真实问题');
  });
  await expect(refresh).toBeDisabled();
  await expect(page.getByText('新版本已就绪，请先发送或保存当前输入。')).toBeVisible();
  await page.evaluate(async () => {
    const path = '/src/store/useStore.ts';
    const { useStore } = await import(path);
    useStore.getState().setDraft('');
  });
  await expect(refresh).toBeEnabled();
});

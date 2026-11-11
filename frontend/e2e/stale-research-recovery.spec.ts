import { expect, test } from '@playwright/test';
import { E2E_SESSION_ID, installAuthenticatedSession } from './helpers/auth';

for (const failed of [false, true]) {
  test(`打开旧会话不会恢复超长计时器：${failed ? '恢复连接失败' : '两条已完成研究'}`, async ({ page }, testInfo) => {
    await page.addInitScript((session) => {
      localStorage.clear();
      localStorage.setItem('finsight-session-id', session);
      sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    }, E2E_SESSION_ID);
    await installAuthenticatedSession(page);
    await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"healthy"}' }));
    const oldTime = Date.now() - 149302000;
    const restoredRuns: string[] = [];
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.fallback();
      const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
      if (path.startsWith('/api/execute/runs/')) {
        const run = path.split('/').at(-1)!;
        restoredRuns.push(run);
        if (failed) return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"temporarily unavailable"}' });
        return json({ run_id: run, session_id: E2E_SESSION_ID, user_message_id: 'u', assistant_message_id: run,
          status: 'completed', created_at: (oldTime + 1000) / 1000,
          result: { type: 'done', response: `已恢复保存的研究结果 ${run}`, answer_status: 'answered' } });
      }
      if (path.startsWith('/api/conversations/') && route.request().method() === 'GET') return json({ success: true,
        session_id: E2E_SESSION_ID, conversation: { messages: [
          { id: 'u', role: 'user', content: '为什么英特尔突然这样暴跌', timestamp: oldTime },
          ...['old-run', 'latest-run'].map((run, index) => ({ id: run, run_id: run, role: 'assistant',
            content: '正在生成回答...', timestamp: oldTime + index + 1, isLoading: true, answer_status: 'running' })),
        ] } });
      if (path === '/api/models') return json({ models: [], default_model_id: null });
      return json({ success: true, session_id: E2E_SESSION_ID, items: [], profile: {}, conversation: { messages: [] } });
    });
    await page.goto('/chat');
    await expect(page.locator('#chat-input')).toBeVisible();
    await page.locator('body').ariaSnapshot();
    if (failed) await expect(page.getByRole('button', { name: '重新研究', exact: true })).toHaveCount(2);
    else await expect(page.locator('#chat-scroll-container')).toContainText('已恢复保存的研究结果 old-run');
    await expect.poll(() => new Set(restoredRuns).size).toBe(2);
    const body = page.locator('#chat-scroll-container');
    await expect(body).not.toContainText('正在生成回答');
    await expect(body).not.toContainText('正在处理你的问题');
    await expect(body).not.toContainText('149302');
    await page.screenshot({ path: testInfo.outputPath(failed ? 'recovery-unavailable.png' : 'recovered-history.png'), animations: 'disabled' });
  });
}

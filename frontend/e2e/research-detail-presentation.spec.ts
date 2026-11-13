import { expect, test } from '@playwright/test';
import { E2E_SESSION_ID, installAuthenticatedSession } from './helpers/auth';

for (const mobile of [false, true]) {
  test(`研究详情与分组来源可读且可折叠：${mobile ? '手机亮色' : '桌面暗色'}`, async ({ page }, testInfo) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 });
    await page.addInitScript(({ session, mobile }) => {
      localStorage.clear();
      localStorage.setItem('finsight-session-id', session);
      localStorage.setItem('finsight-theme', mobile ? 'light' : 'dark');
      sessionStorage.setItem('finsight-welcome-gate-passed', '1');
    }, { session: E2E_SESSION_ID, mobile });
    await installAuthenticatedSession(page);
    await page.route('**/health', (route) => route.fulfill({ contentType: 'application/json', body: '{"status":"healthy"}' }));
    await page.route('**/api/**', (route) => {
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith('/api/')) return route.fallback();
      const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
      if (path.endsWith('/health')) return json({ status: 'healthy' });
      if (path === '/api/models') return json({ models: [], default_model_id: null });
      if (path === '/api/dashboard') return json({ state: { active_asset: { symbol: 'NVDA', display_name: 'NVIDIA', type: 'equity' }, capabilities: {} },
        data: { snapshot: {}, charts: {}, news: { market: [], impact: [] }, valuation: {} } });
      if (path.startsWith('/api/stock/kline/')) return json({ data: { kline_data: [], source: 'fixture' } });
      return json({ success: true, session_id: E2E_SESSION_ID, items: [], profile: {}, conversation: { messages: [] } });
    });
    await page.goto('/chat');
    await expect(page.locator('#chat-input')).toBeVisible();
    await page.evaluate(async () => {
      const path = '/src/store/useStore.ts';
      const { useStore } = await import(/* @vite-ignore */ path);
      const article = { headline: '英伟达公布合作进展', url: 'https://finance.yahoo.com/news/nvidia-partnership',
        source: 'Yahoo', published_at: '2026-11-09', summary: '双方将扩大计算产品合作，具体收入贡献仍需后续披露。', event_quality: { ingest_channel: 'provider_feed' } };
      const event = (stage: string, result: object) => ({ stage, eventType: stage, timestamp: new Date().toISOString(), result });
      useStore.setState({ showRightPanel: false, messages: [
        { id: 'u', role: 'user', content: 'NVDA 最近有什么新闻？', timestamp: Date.now() - 5000 },
        { id: 'a', role: 'assistant', runId: 'presentation-test', timestamp: Date.now() - 4000, runStatus: 'completed',
          content: '最值得关注的是合作扩展。这可能影响产品落地节奏，实际贡献仍需后续披露确认。[Sabc111]\n\n[英伟达公布合作进展](https://finance.yahoo.com/news/nvidia-partnership)',
          thinking: [event('activity.started', { activity_id: 'model_capability', title: '正在验证模型工具能力' }),
            event('activity.finished', { activity_id: 'model_capability', title: '模型工具能力已验证', summary: '已通过工具调用检查，继续研究。' }),
            event('tool.result', { name: 'get_company_news', tool_call_id: 'news', inputs: { ticker: 'NVDA' }, output_preview: [article] }),
            event('tool.result', { name: 'read_evidence', tool_call_id: 'read', inputs: { max_chars: 6000 },
              output_preview: { offset: 0, total_chars: 23993, content: '这是一段读取到的研究资料。\\n' + '相关内容应按完整宽度展示，避免挤成窄条。'.repeat(12) } }),
            event('done', { status: 'completed' })],
          evidence_pool: [
            { source_id: 'Sabc111', title: article.headline, source: 'Yahoo', url: article.url, kind: 'news' },
            { source_id: 'Sabc222', title: '行业供需观察', source: 'ChartMill', url: 'https://chartmill.com/news/industry', kind: 'news' },
            { source_id: 'Sabc333', title: '合作伙伴后续披露', source: 'yfinance', url: 'https://uk.finance.yahoo.com/news/partner', kind: 'news' },
          ] },
      ] });
    });
    const chat = page.locator('#chat-scroll-container');
    expect(await chat.ariaSnapshot()).toContain('最值得关注的是合作扩展');
    const headline = chat.getByRole('link', { name: '英伟达公布合作进展', exact: true });
    await expect(headline).toBeVisible();
    await expect(headline).toHaveAttribute('href', 'https://finance.yahoo.com/news/nvidia-partnership');
    const sources = page.getByTestId('answer-sources');
    await expect(sources).not.toHaveAttribute('open', '');
    await sources.locator('summary').first().click();
    await expect(sources.getByTestId('source-group')).toHaveCount(0);
    await expect(sources.getByRole('link', { name: /合作伙伴后续披露/ })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(mobile ? 'sources-mobile.png' : 'sources-desktop.png'), fullPage: true });
    await sources.locator('summary').first().click();
    await expect(sources.getByRole('link', { name: /合作伙伴后续披露/ })).not.toBeVisible();
    await chat.locator('.turn-activity-toggle').click();
    const model = chat.locator('.tool-activity').filter({ hasText: '模型工具能力已验证' });
    await expect(model).toHaveCount(0);
    const news = chat.locator('.tool-activity').filter({ hasText: '读取公司新闻' });
    await news.locator('summary').first().click();
    await expect(news.getByRole('link', { name: '英伟达公布合作进展' })).toBeVisible();
    await expect(news).not.toContainText('provider_feed');
    const result = news.getByText('结果', { exact: true }).locator('..');
    const detailBox = await news.locator('.tool-activity-details').boundingBox();
    expect((await result.boundingBox())!.width).toBeGreaterThan(detailBox!.width * .8);
    const read = chat.locator('.tool-activity').filter({ hasText: '读取资料' });
    await read.locator('summary').first().click();
    await expect(read).toContainText('这是一段读取到的研究资料');
    const prose = read.locator('dd').filter({ hasText: '这是一段读取到的研究资料' });
    expect((await prose.boundingBox())!.width).toBeGreaterThan((await read.locator('.tool-activity-details').boundingBox())!.width * .8);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(mobile ? 'details-mobile.png' : 'details-desktop.png'), fullPage: true });
    await chat.getByLabel('查看引用 1', { exact: true }).click();
    await expect(page.getByTestId('context-panel')).toBeVisible();
  });
}

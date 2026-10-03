import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

test('独立修复页绕过旧导航缓存并保留登录、模型设置和聊天记录', async ({ page }) => {
  const html=await readFile(new URL('../../backend/api/client_recovery.html', import.meta.url),'utf8');
  const build='a'.repeat(40);
  const server=createServer((request,response) => {
    const path=new URL(request.url || '/', 'http://localhost').pathname;
    response.setHeader('Cache-Control','no-store');
    if (path==='/sw.js') {
      response.setHeader('Content-Type','application/javascript');
      response.end(`self.addEventListener('install',()=>self.skipWaiting());
        self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
        self.addEventListener('fetch',event=>{if(event.request.mode==='navigate'&&!new URL(event.request.url).pathname.startsWith('/api/'))
          event.respondWith(Promise.resolve(new Response('<h1>旧页面仍控制导航</h1>',{headers:{'Content-Type':'text/html; charset=utf-8'}})));});`);
    } else if (path==='/api/client-recovery') {
      response.setHeader('Content-Type','text/html; charset=utf-8');response.end(html);
    } else if (path==='/app-version.json') {
      response.setHeader('Content-Type','application/json');response.end(JSON.stringify({build_id:build}));
    } else {
      response.setHeader('Content-Type','text/html; charset=utf-8');response.end('<h1>当前聊天页面</h1>');
    }
  });
  await new Promise<void>((resolve)=>server.listen(0,'127.0.0.1',resolve));
  const address=server.address();
  if (!address || typeof address==='string') throw new Error('missing_test_address');
  const origin=`http://127.0.0.1:${address.port}`;
  try {
    await page.goto(origin+'/chat');
    await page.evaluate(async () => {
      localStorage.setItem('finsight-session-id','public:fixture:original');
      localStorage.setItem('finsight-messages:public:fixture:original','saved-fixture-answer');
      localStorage.setItem('finsight-model-selection','fixture-model-setting');
      document.cookie='fixture_login=retained; path=/';
      await (await caches.open('finsight-static-assets')).put('/old.js',new Response('old asset'));
      await (await caches.open('workbox-precache-v2-test')).put('/index.html',new Response('old shell'));
      await (await caches.open('unrelated-cache')).put('/keep',new Response('keep'));
      await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller) await new Promise<void>((resolve)=>navigator.serviceWorker.addEventListener('controllerchange',()=>resolve(),{once:true}));
    });
    await page.reload();
    await expect(page.getByRole('heading',{name:'旧页面仍控制导航'})).toBeVisible();
    await page.goto(origin+'/api/client-recovery');
    await expect(page.getByRole('heading',{name:'恢复已保存的回答'})).toBeVisible();
    await page.getByRole('button',{name:'修复页面并打开原会话'}).click();
    await expect(page).toHaveURL(origin+'/chat?client_recovered='+build);
    await expect(page.getByRole('heading',{name:'当前聊天页面'})).toBeVisible();
    const state=await page.evaluate(async()=>({session:localStorage.getItem('finsight-session-id'),
      answer:localStorage.getItem('finsight-messages:public:fixture:original'),model:localStorage.getItem('finsight-model-selection'),
      cookie:document.cookie,caches:await caches.keys(),workers:(await navigator.serviceWorker.getRegistrations()).length}));
    expect(state).toMatchObject({session:'public:fixture:original',answer:'saved-fixture-answer',model:'fixture-model-setting',workers:0});
    expect(state.cookie).toContain('fixture_login=retained');
    expect(state.caches).toEqual(['unrelated-cache']);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve)=>server.close(()=>resolve()));
  }
});

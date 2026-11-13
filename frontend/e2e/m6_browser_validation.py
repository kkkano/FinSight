"""M6 浏览器合同走查；对话为界面协议夹具，图表使用原始真实行情归档。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SESSION = "public:e2e-user:default"

AUTH_MODULE = """
const session = { user: { id: 'e2e-user', email: 'e2e@example.com' } };
const client = { auth: {
  getSession: async () => ({ data: { session } }),
  onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
} };
export const isSupabaseAuthConfigured = () => true;
export const getSupabaseClient = () => client;
"""

INIT = """({session, dark}) => {
  localStorage.clear();
  localStorage.setItem('finsight-theme', dark ? 'dark' : 'light');
  localStorage.setItem('finsight-session-id', session);
  sessionStorage.setItem('finsight-welcome-gate-passed', '1');
  window.__m6 = { sends: 0, pending: false };
  const original = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (!url.endsWith('/api/execute') || init?.method !== 'POST') return original(input, init);
    window.__m6.sends += 1;
    const request = JSON.parse(String(init.body));
    const encoder = new TextEncoder();
    let stopped = false;
    const stream = new ReadableStream({ start(controller) {
      let seq = 0;
      const emit = (event) => { if (!stopped) controller.enqueue(encoder.encode('data: ' + JSON.stringify({
        schema_version: 2, run_id: request.run_id, session_id: request.session_id, seq: ++seq, ...event,
      }) + '\\n\\n')); };
      emit({ type: 'content.delta', payload: { block_id: 'qa-answer', delta: '这段内容仅用于界面验收。' } });
      if (!window.__m6.pending) {
        emit({ type: 'done', response: '这段内容仅用于界面验收。', run_status: 'completed', success: true,
          persistence_status: 'ephemeral', blocks: [{ id: 'qa-answer', kind: 'text', content: '这段内容仅用于界面验收。', revision: 0, seq: 1 }] });
        stopped = true; controller.close();
      }
      init?.signal?.addEventListener('abort', () => {
        if (!stopped) { stopped = true; controller.error(new DOMException('界面验收取消', 'AbortError')); }
      });
    } });
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream', 'X-Run-Id': request.run_id } });
  };
}"""

SEED = """async ({rows, asOf, provider, dark, mode}) => {
  const { useStore } = await import('/src/store/useStore.ts');
  const { useModelSelectionStore } = await import('/src/store/modelSelection.ts');
  const now = Date.now();
  const event = (stage, seq, result, timestamp = now - 3000) => ({ stage, eventType: stage,
    timestamp: new Date(timestamp).toISOString(), result: { ...result, seq } });
  const sources = [1, 2, 3].map((n) => ({ source_id: `Sabc${n}${n}${n}`, title: `界面验收资料 ${n}`,
    source: n === 1 ? provider : '说明资料', url: `https://example.com/ui-qa/${n}`, as_of: asOf }));
  const table = '| 文本列 | 数值列 | 说明 |\\n|---|---:|---|\\n| 中文项目 | 42 | 排版验收 |\\n';
  const wideHeaders = Array.from({ length: 14 }, (_, n) => `字段 ${n + 1}（排版核对）`);
  const wide = '| ' + wideHeaders.join(' | ') + ' |\\n| ' + wideHeaders.map(() => '---').join(' | ')
    + ' |\\n| ' + wideHeaders.map(() => '核对内容').join(' | ') + ' |';
  let answer = '# 一级标题\\n\\n## 二级标题\\n\\n### 三级标题\\n\\n#### 四级标题\\n\\n'
    + '这段文字仅用于界面验收，核对中文、`行内代码`与来源编号[Sabc111]的显示。\\n\\n' + table + '\\n\\n' + wide;
  const artifact = { artifact_id: 'm6-archive-chart', kind: 'chart', title: 'AAPL 归档行情（界面验收）',
    source_refs: ['Sabc111'], spec: { chart_type: 'line', x: 'time', series: [{ field: 'close', name: '收盘价', unit: 'USD' }] },
    data: { rows }, method: { as_of: asOf, frequency: '1d', description: '使用已有真实归档，仅核对显示与数据入口。' } };
  let thinking = [event('activity.started', 1, { activity_id: 'model_capability', title: '正在验证模型工具能力' }),
    event('activity.finished', 2, { activity_id: 'model_capability', status: 'completed' }),
    event('tool.started', 5, { tool_call_id: 'qa-quote', name: 'get_stock_price', inputs: { ticker: 'AAPL' } }),
    event('tool.result', 6, { tool_call_id: 'qa-quote', name: 'get_stock_price', inputs: { ticker: 'AAPL' },
      duration_ms: 420, display: { kind: 'quote', status: 'ok', title: '获取行情', target: 'AAPL', result: '归档资料已取得',
        key_facts: [{ label: '归档收盘价', value: rows.at(-1).close }, { label: '货币', value: 'USD' }] }, sources: [sources[0]] }),
    event('tool.result', 7, { tool_call_id: 'qa-news', name: 'get_company_news', inputs: { ticker: 'AAPL' },
      duration_ms: 320, display: { target: 'AAPL', result: '界面资料已取得' }, output_preview: { source_count: 3 } }),
    event('done', 10, { status: mode === 'partial' ? 'partial' : 'completed' }, now)];
  let blocks = [{ id: 'qa-reasoning', kind: 'reasoning', content: '这段公开说明仅用于界面验收。\\n'.repeat(12),
    reasoning_kind: 'public_summary', agent_label: '主研究员', duration_ms: 1400, revision: 0, seq: 3 },
    { id: 'qa-progress', kind: 'text', content: '正在核对界面与资料入口。', content_phase: 'progress', revision: 0, seq: 4 },
    { id: 'qa-body', kind: 'text', content: answer, revision: 0, seq: 8 },
    { id: 'm6-archive-chart', kind: 'artifact', artifact, revision: 0, seq: 9 }];
  if (mode === 'cap-pending' || mode === 'cap-error') {
    thinking = [event('activity.started', 1, { activity_id: 'model_capability', title: '正在验证模型工具能力' }, now)];
    if (mode === 'cap-error') thinking.push(event('activity.failed', 2, { activity_id: 'model_capability',
      status: 'error', error_code: 'model_tool_calling_unsupported' }, now));
    blocks = []; sources.splice(0); answer = '';
  }
  if (mode === 'running') {
    thinking = thinking.filter(item => item.stage !== 'done');
    thinking.push(event('tool.started', 11, { tool_call_id: 'qa-live', name: 'get_earnings_estimates',
      display: { title: '获取盈利预期', target: 'AAPL' } }, now));
  }
  useStore.getState().setTheme(dark ? 'dark' : 'light');
  useStore.getState().setColorConvention('intl');
  useModelSelectionStore.setState({ metadata: { id: 'system:qa', label: '界面验收模型', native_tool_calls: true,
    supports_tools: true, capability_status: 'supported' } });
  useStore.setState({ showRightPanel: false, isChatLoading: ['cap-pending', 'running'].includes(mode), messages: [
    { id: 'qa-user', role: 'user', content: '界面验收问题', timestamp: now - 4000 },
    { id: 'qa-message', role: 'assistant', content: answer, runId: 'm6-ui-qa', timestamp: now - 3000,
      runStatus: mode === 'cap-pending' ? 'running' : mode === 'cap-error' ? 'failed' : mode,
      isLoading: ['cap-pending', 'running'].includes(mode), thinking, blocks, evidence_pool: sources },
  ] });
}"""


def real_archive() -> tuple[list, str, str, dict]:
    for path in (ROOT / 'tests/agent_eval/fixtures/archive-v1/tapes').glob('*.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['tool'] == 'get_stock_historical_data' and data['arguments'] == {'ticker': 'AAPL', 'period': '1y', 'interval': '1d'}:
            output = data['result']['data']
            rows = output.get('kline_data') or output.get('data')
            if not isinstance(rows, list) or not rows:
                raise ValueError('真实行情归档中没有行数据')
            return rows, output.get('as_of') or '2026-11-06', output.get('source') or output.get('provider') or '来源未注明', {
                'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'row_count': len(rows)}
    raise ValueError('找不到明确的 AAPL 原始行情归档，禁止补造数据')


def install_routes(page, dark):
    # 本轮仅检查界面协议，所有非本机请求都在浏览器内阻断。
    page.route('**/*', lambda route: route.fallback() if urlsplit(route.request.url).hostname in ('127.0.0.1', 'localhost') else route.abort())
    page.add_init_script('(' + INIT + ')(' + json.dumps({'session': SESSION, 'dark': dark}) + ')')
    page.route('**/src/api/supabaseClient.ts*', lambda route: route.fulfill(status=200, content_type='application/javascript', body=AUTH_MODULE))
    page.route('**/health', lambda route: route.fulfill(content_type='application/json', body='{"status":"healthy"}'))

    def api(route):
        if not urlsplit(route.request.url).path.startswith('/api/'):
            return route.fallback()
        path = route.request.url.split('/api/', 1)[-1].split('?', 1)[0]
        body = {'success': True, 'user_id': 'e2e-user', 'session_id': SESSION, 'items': [], 'count': 0,
                'profile': {}, 'conversation': {'messages': []}, 'watchlist': []}
        if path == 'models':
            body = {'models': [{'id': 'system:qa', 'model': 'ui-qa', 'label': '界面验收模型', 'available': True,
                               'native_tool_calls': True, 'supports_tools': True, 'effort_options': []}], 'default_model_id': 'system:qa'}
        elif path == 'dashboard':
            body = {'state': {'active_asset': {'symbol': 'AAPL', 'type': 'equity'}, 'capabilities': {}},
                    'data': {'snapshot': {}, 'charts': {}, 'news': {'market': [], 'impact': []}, 'valuation': {}}}
        elif path == 'capabilities':
            body = {'ready': True, 'features': {}}
        route.fulfill(content_type='application/json', body=json.dumps(body))

    page.route('**/api/**', api)


def colors(page):
    return page.evaluate("""() => {
      const style = getComputedStyle(document.documentElement);
      const result = Object.fromEntries(['bg','text-2','up','down','warning','success','error'].map(key => [key, style.getPropertyValue('--t-' + key).trim()]));
      const probe = document.createElement('span'); probe.className = 'text-t-success'; document.body.append(probe);
      result.check = getComputedStyle(probe).color; probe.remove();
      return result;
    }""")


def contrast(a, b):
    def luminance(color):
        if color.startswith('#'):
            channels = [int(color.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        else:
            values = color.removeprefix('rgba(').removeprefix('rgb(').removesuffix(')').split(',')
            channels = [float(value.strip()) / 255 for value in values[:3]]
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))
    x, y = sorted((luminance(a), luminance(b)))
    return (y + .05) / (x + .05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:4273')
    parser.add_argument('--output', default=str(ROOT / 'frontend/test-results/m6-native'))
    parser.add_argument('--validation', help='本次定向单测与构建的命令、退出码和产物 JSON')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('验收产物只能写入工作树')
    output.mkdir(parents=True, exist_ok=True)
    rows, as_of, provider, provenance = real_archive()
    source_paths = sorted(path for path in (ROOT / 'frontend/src').rglob('*') if path.is_file())
    source_paths += [Path(__file__), *(ROOT / 'frontend' / name for name in ('package.json', 'package-lock.json', 'vite.config.ts', 'tailwind.config.js'))]
    hashes = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    evidence = {'source': provenance, 'checks': [], 'screenshots': [], 'model_quality_evaluation': False,
                'started_at_utc': datetime.now(timezone.utc).isoformat(), 'source_sha256': hashes,
                'scope': '本机浏览器界面协议样本；图表复用真实归档。不是线上真实金融或模型质量验收。',
                'backend_started': False, 'live_model_calls': False}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        try:
            for dark, width in [(False, 1440), (True, 1440), (False, 390), (True, 390)]:
                context = browser.new_context(viewport={'width': width, 'height': 960}, reduced_motion='reduce',
                                              is_mobile=width == 390, has_touch=width == 390)
                page = context.new_page()
                browser_errors = []
                page.on('pageerror', lambda error: browser_errors.append(str(error)))
                install_routes(page, dark)
                page.goto(args.url + '/chat')
                page.wait_for_load_state('networkidle')
                if page.locator('#chat-input').count() == 0:
                    page.screenshot(path=str(output / 'initial-failure.png'))
                    print(json.dumps({'url': page.url, 'errors': browser_errors, 'body': page.locator('body').inner_text()[:1200]}, ensure_ascii=False))
                expect(page.locator('#chat-input')).to_be_visible()
                evidence['initial_dom'] = page.locator('body').aria_snapshot()[:1200]
                payload = {'rows': rows, 'asOf': as_of, 'provider': provider, 'dark': dark, 'mode': 'completed'}
                page.evaluate(SEED, payload)
                expect(page.locator('.fs-prose h1')).to_be_visible()
                chat = page.locator('#chat-scroll-container')
                chat.evaluate('(node) => { node.scrollTop = 0; }')
                typography = page.locator('.fs-prose').evaluate("""node => {
                  const size = selector => Number.parseFloat(getComputedStyle(node.querySelector(selector)).fontSize);
                  const td = node.querySelector('table td:nth-child(2)'); const th = node.querySelector('table th:nth-child(2)');
                  return { h1:size('h1'), h2:size('h2'), h3:size('h3'), h4:size('h4'), body:Number.parseFloat(getComputedStyle(node).fontSize),
                    code:getComputedStyle(node.querySelector('code')).color, codeBefore:getComputedStyle(node.querySelector('code'),'::before').content,
                    td:getComputedStyle(td).textAlign, th:getComputedStyle(th).textAlign, font:getComputedStyle(document.body).fontFamily };
                }""")
                assert typography['h1'] == 17 and typography['h2'] == 16 and typography['h3'] == 14.5
                assert typography['h4'] == 13
                assert typography['body'] == 14.5 and typography['codeBefore'] in ('none', 'normal', '""')
                assert typography['th'] == typography['td'] == 'right'
                assert 'Geist Variable' in typography['font']
                overflow = page.evaluate('({page: document.documentElement.scrollWidth, viewport: innerWidth})')
                assert overflow['page'] <= overflow['viewport'], overflow
                assert page.locator('.tool-activity-row').count() == 0
                assert page.get_by_test_id('reasoning-block').count() == 0
                collapsed_name = f"{'dark' if dark else 'light'}-{width}-collapsed.png"
                page.screenshot(path=str(output / collapsed_name), full_page=False)
                evidence['screenshots'].append(collapsed_name)
                toggle = chat.locator('.turn-activity-toggle')
                toggle.focus(); page.keyboard.press('Enter')
                expect(toggle).to_have_attribute('aria-expanded', 'true')
                focus = toggle.evaluate('(node) => ({visible:node.matches(":focus-visible"), style:getComputedStyle(node).outlineStyle, width:getComputedStyle(node).outlineWidth})')
                assert focus['visible'] and focus['style'] != 'none' and focus['width'] != '0px', focus
                expect(chat.locator('.tool-activity-row')).to_have_count(2)
                tool_layout = chat.locator('.tool-activity-row').evaluate_all("""nodes => nodes.map(node => {
                  const target = node.querySelector('.tool-activity-target'), summary = node.querySelector('.tool-activity-summary');
                  const context = target.parentElement;
                  return { columns: getComputedStyle(node).gridTemplateColumns.split(' ').length,
                    contextDisplay: getComputedStyle(context).display, distinctCells: target !== summary && summary.parentElement === context,
                    target: target.textContent, targetFont: getComputedStyle(target).fontFamily,
                    name: node.querySelector('.tool-activity-name').textContent, summary: summary.textContent,
                    summaryWrap:getComputedStyle(summary).whiteSpace, summaryOverflow:getComputedStyle(summary).textOverflow };
                })""")
                assert all(item['columns'] == 5 and item['contextDisplay'] == 'grid' and item['distinctCells']
                           and item['target'] == 'AAPL' and 'JetBrains Mono' in item['targetFont']
                           and item['name'] and item['summary'] and item['summaryWrap'] == 'nowrap'
                           and item['summaryOverflow'] == 'ellipsis' for item in tool_layout), tool_layout
                quote = chat.locator('.tool-activity').filter(has_text='获取行情')
                quote.locator('summary').click()
                expect(quote.get_by_text('归档收盘价', exact=True)).to_be_visible()
                quote.locator('summary').click()
                expect(chat.locator('.tool-activity').filter(has_text='模型工具能力已验证')).to_have_count(0)
                reasoning = chat.get_by_test_id('reasoning-block').locator('button')
                reasoning.focus(); page.keyboard.press('Enter')
                expect(reasoning).to_have_attribute('aria-expanded', 'true')
                lefts = page.evaluate("""() => ['.tool-activity-row', '[data-testid="research-progress"]', '[data-testid="reasoning-block"] button']
                  .map(selector => document.querySelector(selector).getBoundingClientRect().left)""")
                assert max(lefts) - min(lefts) < 1, lefts
                source_list = page.get_by_test_id('answer-sources')
                source_list.locator('summary').first.focus(); page.keyboard.press('Enter')
                expect(source_list.get_by_test_id('source-group')).to_have_count(0)
                assert source_list.get_by_role('link').count() == 3
                expect(chat.get_by_role('button', name='重新研究', exact=True)).to_be_visible()
                wrappers = page.locator('.fs-prose table').evaluate_all('(nodes) => nodes.map(node => ({width:node.parentElement.clientWidth, scroll:node.parentElement.scrollWidth}))')
                if width == 390:
                    assert any(item['scroll'] > item['width'] for item in wrappers), wrappers
                chat.evaluate('(node) => { node.scrollTop = node.scrollHeight; }')
                expect(chat.get_by_role('button', name='回到最新', exact=True)).to_have_count(0)
                before = chat.evaluate('(node) => node.scrollHeight')
                chat.evaluate('(node) => { node.scrollTop = 0; }')
                expect(chat.get_by_role('button', name='回到最新', exact=True)).to_be_visible()
                after = chat.evaluate('(node) => node.scrollHeight')
                assert after == before
                page.locator('#chat-input').fill('下一条界面验收问题')
                expect(page.get_by_test_id('chat-send-btn')).to_be_enabled()
                normal = colors(page)
                page.evaluate("async () => { const {useStore}=await import('/src/store/useStore.ts');useStore.getState().setColorConvention('cn'); }")
                cn = colors(page)
                assert cn['up'] == normal['down'] and cn['down'] == normal['up']
                assert cn['success'] == normal['success'] and cn['error'] == normal['error'] and cn['check'] == normal['check']
                ratios = {key: contrast(normal[key], normal['bg']) for key in ('text-2', 'up', 'down', 'warning')}
                assert all(value >= 4.5 for value in ratios.values()), ratios
                send = page.get_by_test_id('chat-send-btn').evaluate('(node) => ({color:getComputedStyle(node).color,bg:getComputedStyle(node).backgroundColor})')
                if dark:
                    assert send['color'] == 'rgb(14, 16, 20)', send
                send_contrast = contrast(send['color'], send['bg'])
                assert send_contrast >= 3, send
                name = f"{'dark' if dark else 'light'}-{width}.png"
                page.screenshot(path=str(output / name), full_page=False)
                evidence['screenshots'].append(name)
                evidence['checks'].append({'theme': 'dark' if dark else 'light', 'width': width, 'typography': typography,
                                          'track_lefts': lefts, 'contrast': ratios, 'normal_colors': normal, 'cn_colors': cn,
                                          'send': send, 'send_contrast': send_contrast, 'overflow': overflow,
                                          'table_wrappers': wrappers, 'jump_scroll_height': {'before': before, 'after': after},
                                          'tool_layout': tool_layout, 'keyboard_focus': focus, 'reduced_motion': page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")})
                context.close()

            context = browser.new_context(viewport={'width': 1440, 'height': 960})
            page = context.new_page(); install_routes(page, False)
            page.goto(args.url + '/chat'); page.wait_for_load_state('networkidle')
            page.locator('body').aria_snapshot()
            payload = {'rows': rows, 'asOf': as_of, 'provider': provider, 'dark': False, 'mode': 'cap-pending'}
            page.evaluate(SEED, payload)
            expect(page.locator('.tool-activity-row')).to_have_count(0)
            expect(page.locator('.tool-activity-row')).to_have_count(1, timeout=4000)
            expect(page.locator('.turn-activity-toggle')).to_contain_text('正在验证模型能力')
            page.evaluate(SEED, {**payload, 'mode': 'cap-error'})
            page.locator('.turn-activity-toggle').click()
            page.locator('.tool-activity-row').click()
            expect(page.get_by_role('button', name='更换模型', exact=True)).to_be_visible()
            page.get_by_role('button', name='更换模型', exact=True).click()
            expect(page.get_by_role('dialog')).to_be_visible()
            page.get_by_role('button', name='关闭设置', exact=True).click()
            page.evaluate(SEED, {**payload, 'mode': 'completed'})
            page.get_by_test_id('context-panel-expand').click()
            panel = page.get_by_test_id('context-panel')
            panel.get_by_role('button', name='AAPL', exact=True).click()
            page.evaluate("""async () => {
              const {useStore}=await import('/src/store/useStore.ts');
              useStore.setState({messages:[...useStore.getState().messages,{id:'qa-topic-change',role:'assistant',runId:'qa-next',
                content:'这段测试文字提到 TSLA，主体仍来自工具参数。',timestamp:Date.now(),thinking:[
                  {stage:'tool.result',timestamp:new Date().toISOString(),result:{inputs:{ticker:'NVDA'}}}],blocks:[]}]});
            }""")
            expect(panel.get_by_role('button', name='AAPL', exact=True)).to_have_attribute('aria-pressed', 'true')
            expect(panel.get_by_role('button', name='NVDA', exact=True)).to_have_attribute('aria-pressed', 'false')
            expect(panel.get_by_role('button', name='TSLA', exact=True)).to_have_count(0)
            panel.get_by_role('button', name='收起面板', exact=True).click()
            page.evaluate(SEED, {**payload, 'mode': 'partial'})
            expect(page.locator('.turn-activity-toggle')).to_contain_text('已有部分结果，但资料还不完整')
            page.locator('#chat-input').fill('输入法组合中的界面问题')
            before = page.evaluate('window.__m6.sends')
            page.locator('#chat-input').dispatch_event('keydown', {'key': 'Enter', 'code': 'Enter', 'isComposing': True, 'keyCode': 229})
            assert page.evaluate('window.__m6.sends') == before
            page.evaluate('window.__m6.pending = true')
            page.locator('#chat-input').focus(); page.keyboard.press('Enter')
            expect(page.get_by_test_id('chat-stop-btn')).to_be_visible()
            page.get_by_test_id('chat-stop-btn').focus(); page.keyboard.press('Enter')
            expect(page.locator('.turn-activity-toggle').last).to_contain_text('已停止，保留已生成内容')
            assert page.evaluate('window.__m6.sends') == before + 1
            page.evaluate(SEED, {**payload, 'mode': 'running'})
            status = page.get_by_test_id('research-status')
            expect(status).to_have_attribute('aria-live', 'polite')
            expect(status).to_have_attribute('aria-atomic', 'true')
            expect(status).to_have_text('正在获取盈利预期…')
            page.evaluate("""() => {
              const node = document.querySelector('[data-testid="research-status"]');
              window.__m6.announcements = [];
              window.__m6.statusObserver = new MutationObserver(() => window.__m6.announcements.push(node.textContent));
              window.__m6.statusObserver.observe(node, {subtree:true, characterData:true, childList:true});
            }""")
            timer_before = page.locator('.turn-activity-toggle').inner_text()
            page.evaluate("""async () => {
              const {useStore} = await import('/src/store/useStore.ts');
              useStore.setState({messages: useStore.getState().messages.map(message => message.id !== 'qa-message' ? message : {
                ...message, content:message.content+'正文增量', blocks:message.blocks.map(block =>
                  block.kind === 'text' || block.kind === 'reasoning' ? {...block,content:block.content+'逐字增量'} : block)
              })});
            }""")
            page.wait_for_timeout(2200)  # 验证真实计时更新不会改变 live region。
            assert page.locator('.turn-activity-toggle').inner_text() != timer_before
            assert page.evaluate('window.__m6.announcements') == []
            page.evaluate("""async () => {
              const {useStore} = await import('/src/store/useStore.ts');
              useStore.setState({messages:useStore.getState().messages.map(message => message.id !== 'qa-message' ? message : {
                ...message,thinking:[...message.thinking,{stage:'tool.started',eventType:'tool.started',timestamp:new Date().toISOString(),
                  result:{seq:12,tool_call_id:'qa-next',name:'get_company_news',display:{title:'读取公司新闻',target:'AAPL'}}}]
              })});
            }""")
            expect(status).to_have_text('正在读取公司新闻…')
            page.evaluate(SEED, {**payload, 'mode': 'partial'})
            expect(status).to_have_text('已有部分结果，但资料还不完整')
            announcements = page.evaluate('window.__m6.announcements')
            assert announcements == ['正在读取公司新闻…', '已有部分结果，但资料还不完整'], announcements
            page.evaluate('window.__m6.statusObserver.disconnect()')
            evidence['controls'] = {'capability_delay': True, 'capability_failure_model_action': True, 'partial_caption': True,
                                    'ime_enter_not_sent': True, 'keyboard_send_and_stop': True, 'keyboard_expand_sources': True,
                                    'pinned_ticker_survives_topic_change': True, 'ticker_comes_from_tool_parameters': True,
                                    'aria_live_atomic': True, 'no_token_or_timer_announcements': True,
                                    'activity_and_terminal_announcements': announcements}
            context.close()
        finally:
            browser.close()
    assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest for path, digest in hashes.items()), '验收过程中前端源码发生改变，需重新验收'
    evidence['completed_at_utc'] = datetime.now(timezone.utc).isoformat()
    evidence['acceptance_8_6'] = {str(number): {'status': 'passed', 'evidence': reference} for number, reference in enumerate([
        'checks.typography + collapsed screenshots', 'checks.normal_colors/cn_colors', 'checks.contrast/send_contrast',
        'checks.track_lefts + collapsed/expanded screenshots', 'checks.jump_scroll_height',
        'checks.overflow/table_wrappers/tool_layout', 'checks.keyboard_focus/reduced_motion + controls',
        'validation_gate',
    ], 1)}
    if args.validation:
        gate = json.loads(Path(args.validation).read_text(encoding='utf-8'))
        assert gate['unit']['exit_code'] == gate['build']['exit_code'] == 0, gate
        evidence['validation_gate'] = gate
    else:
        evidence['acceptance_8_6']['8'] = {'status': 'unverified', 'reason': '未提供本次定向单测与构建命令证据'}
    (output / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'theme_width_cases': len(evidence['checks']), 'controls': evidence['controls'],
                      'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()

"""M8 原生浏览器界面合同走查；研究与身份为协议夹具，行情来自既有真实归档。"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright
from m6_browser_validation import real_archive

ROOT = Path(__file__).resolve().parents[2]
SESSION = 'public:e2e-user:default'
AUTH_MODULE = """
const session = { access_token:'ui-contract-token', user:{id:'e2e-user',email:'ui-contract@example.test'} };
const client = {auth:{getSession:async()=>({data:{session}}),
onAuthStateChange:()=>({data:{subscription:{unsubscribe(){}}}}),signOut:async()=>({error:null})}};
export const isSupabaseAuthConfigured=()=>true;
export const getSupabaseClient=()=>client;
"""
INIT = """({session,dark})=>{
  if(!localStorage.getItem('finsight-theme'))localStorage.setItem('finsight-theme',dark?'dark':'light');
  if(!localStorage.getItem('finsight-session-id'))localStorage.setItem('finsight-session-id',session);
  sessionStorage.setItem('finsight-welcome-gate-passed','1');
}"""


def fixtures(rows, as_of, provider):
    close = rows[-1]['close']
    report = {'report_id': 'm8-protocol-report', 'title': '界面协议夹具：已分享研究', 'ticker': 'AAPL',
              'company_name': 'Apple', 'summary': '这份报告只用于页面合同验收，不代表真实模型研究。',
              'sentiment': 'neutral', 'confidence_score': None, 'generated_at': '2025-01-01T00:00:00Z',
              'sections': [], 'citations': [{'source_id': 'S1', 'title': '已有行情归档',
              'url': 'https://www.nasdaq.com/market-activity/stocks/aapl', 'snippet': '', 'published_date': as_of[:10]}]}
    prediction = {'prediction_id': 'm8-protocol-prediction', 'run_id': 'm8-protocol-run', 'symbol': 'AAPL',
                  'agent': 'technical', 'direction': 'neutral', 'confidence': 0.5,
                  'thesis': '界面协议夹具，不代表真实模型判断。', 'anchor': {'timeframe': '1d', 'time': as_of, 'price': close},
                  'scenarios': [{'name': '界面合同', 'probability': 50, 'invalidation': '结构化失效字段，用于界面验收。'}],
                  'status': 'open', 'prompt_version': 'ui-contract', 'source_type': 'ai',
                  'created_at': as_of, 'updated_at': as_of, 'evidence_provider': provider, 'evidence_as_of': as_of}
    stats = {'days': 90, 'symbol': None, 'predictions': 1, 'resolved': 0, 'hits': 0, 'misses': 0,
             'invalidated': 0, 'hit_rate': None, 'by_source': {}, 'by_direction': {}}
    return report, prediction, stats


def install_routes(page, dark, rows, as_of, provider, anonymous=False):
    page.add_init_script('(' + INIT + ')(' + json.dumps({'session': SESSION, 'dark': dark}) + ')')
    auth = AUTH_MODULE.replace("const session = { access_token:'ui-contract-token', user:{id:'e2e-user',email:'ui-contract@example.test'} };", 'const session=null;') if anonymous else AUTH_MODULE
    page.route('**/src/api/supabaseClient.ts*', lambda route: route.fulfill(content_type='application/javascript', body=auth))
    page.route('**/health', lambda route: route.fulfill(content_type='application/json', body='{"status":"healthy"}'))
    report, prediction, stats = fixtures(rows, as_of, provider)
    requests = []
    switches = {'report_error': False}

    def api(route):
        request = route.request
        url = urlsplit(request.url)
        if not url.path.startswith('/api/'):
            return route.fallback()
        path = url.path[5:]
        body = {'success': True, 'items': [], 'count': 0, 'watchlist': [], 'profile': {},
                'messages': [], 'conversation': {'messages': []}, 'session_id': SESSION}
        status = 200
        if path == 'models':
            body = {'models': [{'id': 'system:ui-contract', 'label': '界面合同模型', 'model': 'ui-contract',
                    'provider': 'ui-contract', 'available': True, 'native_tool_calls': True, 'supports_tools': True,
                    'capability_status': 'supported', 'effort_options': []}], 'default_model_id': 'system:ui-contract'}
        elif path == 'auth/providers':
            body = {'github_login_enabled': False}
        elif path == 'watchlist':
            body = {'items': [{'ticker': 'AAPL', 'note': '已有归档行情', 'added_at': as_of}]}
        elif path.startswith('stock/price/'):
            body = {'success': True, 'data': {'ticker': path.rsplit('/', 1)[-1], 'price': rows[-1]['close'],
                    'currency': 'USD', 'source': provider, 'provider': provider, 'as_of': as_of, 'status': 'ok'}}
        elif path.startswith('stock/kline/'):
            converted = [{**row, 'time': row.get('time') or row.get('date')} for row in rows]
            period = parse_qs(url.query).get('period', ['1y'])[0]
            months = {'1mo': 1, '3mo': 3, '6mo': 6, '1y': 12}.get(period, 12)
            end = date.fromisoformat(converted[-1]['time'][:10])
            year, month = divmod(end.year * 12 + end.month - 1 - months, 12)
            cutoff = date(year, month + 1, min(end.day, calendar.monthrange(year, month + 1)[1]))
            converted = [row for row in converted if row['time'][:10] >= cutoff.isoformat()]
            body = {'success': True, 'data': {'kline_data': converted, 'provider': provider, 'as_of': as_of}}
        elif path == 'dashboard':
            meta = {'provider': provider, 'as_of': as_of, 'source_type': 'archive', 'status': 'ok',
                    'currency': 'USD', 'time_range': {'start': rows[0].get('time') or rows[0].get('date'), 'end': as_of, 'period': '1y'},
                    'data_refs': ['existing-ui-contract-reference']}
            body = {'state': {'active_asset': {'symbol': 'AAPL', 'display_name': 'Apple', 'type': 'equity'}, 'capabilities': {}},
                    'data': {'snapshot': {'price': rows[-1]['close']}, 'charts': {}, 'valuation': {},
                    'news': {'market': [], 'impact': []}, 'meta': {key: meta for key in ['market_chart', 'valuation', 'financials', 'technicals', 'news_market']}}}
        elif path == 'predictions/history':
            body = {'items': [{'prediction': prediction, 'outcome': None}], 'count': 1}
        elif path == 'predictions/stats':
            body = {'stats': stats}
        elif path.startswith('predictions/runs/'):
            body = {'id': 'm8-protocol-run', 'status': 'succeeded', 'llm_provider': 'ui-contract',
                    'llm_model': '界面合同模型', 'market_provider': provider, 'market_as_of': as_of}
        elif path == 'reports/index':
            if switches['report_error']:
                status, body = 503, {'detail': {'code': 'store_unavailable', 'message': 'Private English traceback'}}
            else:
                body = {'items': [{**report, 'session_id': SESSION, 'created_at': report['generated_at']}], 'count': 1}
        elif path.startswith('reports/replay/'):
            body = {'session_id': SESSION, 'report': report, 'citations': report['citations'], 'trace_digest': {}}
        elif path.startswith('reports/shared/'):
            body = {'report': report, 'published_at': '2026-11-11T01:00:00Z'}
        elif path == 'benchmarks/us20-v1/track-record':
            days = parse_qs(url.query).get('days', [None])[0]
            body = {'enabled': False, 'universe': {'version': 'ui-contract', 'tickers': ['AAPL']},
                    'coverage': {'batch_date': None, 'expected': 0, 'accepted': 0, 'counts': {}, 'attempts': 0, 'last_update': None},
                    'summary': {'opportunities': 0, 'predictions': 0, 'settled': 0, 'pending': 0, 'failed': 0,
                    'missed': 0, 'abstained': 0, 'awaiting_data': 0, 'batch_count': 0, 'stock_count': 1},
                    'groups': [], 'records': [], 'metadata': {'source': provider, 'horizon_sessions': 5,
                    'direction_threshold': 0.005, 'drawdown_threshold': 0.03, 'frequency': 'trading_day',
                    'window_days': int(days) if days else None}, 'daily_series': []}
        elif path == 'execute':
            requests.append(request.post_data_json)
            return route.fulfill(content_type='text/event-stream', body='data: {"type":"done","response":"界面协议夹具回复","persistence_status":"ephemeral"}\n\n')
        route.fulfill(status=status, content_type='application/json', body=json.dumps(body))

    page.route('**/api/**', api)
    return requests, switches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:4278')
    parser.add_argument('--output', default=str(ROOT / 'frontend/test-results/m8-native'))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('验收产物只能写入工作树')
    output.mkdir(parents=True, exist_ok=True)
    rows, as_of, provider, provenance = real_archive()
    evidence = {'model_quality_evaluation': False, 'identity_and_reports': 'UI protocol fixtures',
                'market_archive': provenance, 'pages': [], 'controls': {}, 'screenshots': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        try:
            for dark in [False, True]:
                for width in [1440, 768, 390]:
                    context = browser.new_context(service_workers='block',viewport={'width': width, 'height': 960}, reduced_motion='reduce',
                                                  is_mobile=width == 390, has_touch=width == 390)
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    requests, switches = install_routes(page, dark, rows, as_of, provider)
                    for name, path in [('today', '/today'), ('dashboard', '/dashboard/AAPL'), ('history', '/history?view=predictions'),
                                       ('track-record', '/track-record'), ('personal', '/track-record?scope=personal'), ('share', '/share/r/ui-contract')]:
                        page.goto(args.url + path)
                        page.wait_for_load_state('networkidle')
                        snapshot = page.locator('body').aria_snapshot()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width)
                        assert not errors, errors
                        if name == 'dashboard':
                            expect(page.get_by_role('heading', name='关键指标', exact=True)).to_be_visible()
                            chart = page.get_by_role('region', name='股价走势').locator('canvas')
                            expect(chart).to_be_visible()
                            assert chart.evaluate('(canvas)=>canvas.getContext("2d").getImageData(0,0,canvas.width,canvas.height).data.some((value,index)=>index%4===3&&value>0)')
                            evidence['controls']['archive_chart_drawn'] = True
                        elif name == 'today':
                            expect(page.get_by_text('结构化失效字段，用于界面验收。', exact=True)).to_be_visible()
                        elif name == 'history':
                            expect(page.get_by_role('tab', name='对话判断')).to_be_visible()
                            expect(page.get_by_test_id('answer-sources')).to_be_visible()
                        elif name == 'track-record':
                            expect(page.get_by_text('最近 84 天 · 已结算 0 条', exact=True).first).to_be_visible()
                            expect(page.get_by_text('公开统计', exact=True)).to_be_visible()
                        elif name == 'personal':
                            expect(page.get_by_role('heading', name='我的记录', exact=True)).to_be_visible()
                        elif name == 'share':
                            expect(page.get_by_role('heading', name='界面协议夹具：已分享研究').first).to_be_visible()
                            expect(page.get_by_text('1 个来源', exact=True)).to_be_visible()
                            assert '2026' in page.locator('header').first.inner_text()
                            assert '2025' not in page.locator('header').first.inner_text()
                            assert '分析执行' not in snapshot and '执行详情' not in snapshot
                            assert 'DEEP RESEARCH' not in snapshot and 'Freshness' not in snapshot
                        filename = f"{'dark' if dark else 'light'}-{width}-{name}.png"
                        page.screenshot(path=str(output / filename), full_page=True)
                        evidence['screenshots'].append(filename)
                        evidence['pages'].append({'theme': 'dark' if dark else 'light', 'width': width, 'page': name,
                                                  'no_page_overflow': True, 'snapshot': snapshot[:1000]})
                    context.close()

            context = browser.new_context(service_workers='block',viewport={'width': 1440, 'height': 960}, reduced_motion='reduce')
            page = context.new_page(); requests, switches = install_routes(page, False, rows, as_of, provider)
            page.goto(args.url + '/bad-link'); page.wait_for_load_state('networkidle')
            expect(page).to_have_url(args.url + '/today')
            page.goto(args.url + '/chat'); page.wait_for_load_state('networkidle')
            page.locator('body').aria_snapshot()
            page.get_by_test_id('sidebar-nav-settings').click()
            expect(page.get_by_label('自选增删免确认')).not_to_be_checked()
            expect(page.get_by_label('显示供应商原始推理')).not_to_be_checked()
            page.get_by_label('自选增删免确认').check(); page.get_by_label('显示供应商原始推理').check()
            page.get_by_role('button', name='关闭设置', exact=True).click()
            page.reload(); page.wait_for_load_state('networkidle')
            page.get_by_test_id('sidebar-nav-settings').click()
            expect(page.get_by_label('自选增删免确认')).to_be_checked()
            expect(page.get_by_label('显示供应商原始推理')).to_be_checked()
            page.screenshot(path=str(output / 'settings-persisted.png'), full_page=True)
            evidence['screenshots'].append('settings-persisted.png')
            page.get_by_role('button', name='关闭设置', exact=True).click()
            page.locator('#chat-input').fill('界面合同设置请求'); page.get_by_test_id('chat-send-btn').click()
            expect(page.get_by_text('界面协议夹具回复', exact=True).first).to_be_visible()
            assert requests[-1]['context']['watchlist_auto_confirm'] is True
            assert requests[-1]['context']['show_provider_reasoning'] is True
            page.goto(args.url + '/dashboard/AAPL'); page.wait_for_load_state('networkidle')
            page.locator('body').aria_snapshot()
            page.get_by_role('region', name='关键指标').get_by_role('button', name='问 AI').first.click()
            page.locator('#chat-input').fill('界面合同指标请求'); page.get_by_test_id('chat-send-btn').click()
            expect(page.get_by_text('界面协议夹具回复', exact=True).first).to_be_visible()
            assert requests[-1]['context']['selected_metric']['id'] == 'market_cap'
            assert requests[-1]['context']['data_refs'] == ['existing-ui-contract-reference']
            page.goto(args.url + '/history'); page.wait_for_load_state('networkidle')
            page.locator('body').aria_snapshot(); switches['report_error'] = True
            page.get_by_role('tab', name='研究报告').click()
            expect(page.get_by_role('alert')).to_contain_text('记录存储暂时不可用')
            assert 'Private English traceback' not in page.get_by_role('alert').aria_snapshot()
            switches['report_error'] = False
            page.get_by_role('button', name='重试', exact=True).click()
            expect(page.get_by_test_id('report-history-item')).to_be_visible()
            evidence['controls'].update({'signed_in_unknown_route': True, 'preferences_default_off': True, 'preferences_persisted': True,
                'request_preferences': True, 'dashboard_metric_context': True, 'history_error_retry': True})
            context.close()

            context = browser.new_context(service_workers='block',viewport={'width': 390, 'height': 960}, reduced_motion='reduce')
            page = context.new_page(); install_routes(page, False, rows, as_of, provider, anonymous=True)
            page.goto(args.url + '/welcome'); page.wait_for_load_state('networkidle')
            page.locator('body').aria_snapshot()
            expect(page.get_by_text('示例', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='GitHub', exact=False)).to_have_count(0)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output / 'welcome-anonymous-390.png'), full_page=True)
            evidence['screenshots'].append('welcome-anonymous-390.png')
            page.goto(args.url + '/share/r/ui-contract'); page.wait_for_load_state('networkidle')
            expect(page.get_by_text('只读', exact=True)).to_be_visible()
            page.goto(args.url + '/bad-link'); page.wait_for_load_state('networkidle')
            expect(page).to_have_url(args.url + '/welcome')
            evidence['controls'].update({'anonymous_share': True, 'github_disabled': True, 'welcome_example': True, 'anonymous_unknown_route': True})
            context.close()
        finally:
            browser.close()
    (output / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'page_cases': len(evidence['pages']), 'controls': evidence['controls'], 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()

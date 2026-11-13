"""M9 图表分派与引用协议的界面合同；行情来自真实归档，不运行模型。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from m6_browser_validation import real_archive
from m8_browser_validation import install_routes

ROOT = Path(__file__).resolve().parents[2]
SEED = """async ({rows,asOf,provider,mode,dark})=>{
  const {useStore}=await import('/src/store/useStore.ts');
  const source={source_id:'3',source:provider,title:'已有真实行情归档',as_of:asOf,
    url:'https://www.nasdaq.com/market-activity/stocks/aapl'};
  const marker='[CHART:AAPL:line:close:1y]';
  const inline='<chart type="candlestick" symbol="AAPL" title="旧图表">{"labels":["D1"],"values":[999999]}</chart>';
  const content='界面协议夹具；图表使用已有真实行情归档，引用[3]。\\n\\n'+(mode==='legacy-marker'?marker:mode==='legacy-inline'?inline:marker+'\\n\\n'+inline);
  const artifact={artifact_id:'m9-archive-chart',kind:'chart',title:'界面合同图表 · 真实行情归档',source_refs:['3'],
    spec:{chart_type:'line',x:'time',series:[{field:'close',name:'收盘价',unit:'USD'}]},
    data:{rows:rows.map(row=>({...row,time:row.time||row.date}))},method:{as_of:asOf}};
  const message={id:'m9-ui-answer',role:'assistant',content,timestamp:Date.now(),runId:'m9-ui-protocol',runStatus:'completed',
    evidence_pool:[source],thinking:[{id:'ui-activity',seq:1,stage:'tool.result',eventType:'tool.result',
      timestamp:new Date().toISOString(),result:{tool_call_id:'ui-activity',name:'get_stock_historical_data',inputs:{ticker:'AAPL'},
        display:{kind:'timeseries',status:'ok',title:'获取历史行情',target:'AAPL',result:'界面协议活动夹具'}}}]};
  if(mode==='research')message.blocks=[{id:'body',kind:'text',content,revision:0,seq:2},
    {id:artifact.artifact_id,kind:'artifact',artifact,revision:0,seq:3}];
  if(mode==='empty-blocks')message.blocks=[];
  useStore.getState().setTheme(dark?'dark':'light');
  useStore.setState({showRightPanel:false,isChatLoading:false,messages:[
    {id:'m9-ui-user',role:'user',content:'界面合同走查，非真实模型研究',timestamp:Date.now()-1000},message]});
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:4289')
    parser.add_argument('--output', default=str(ROOT / 'frontend/test-results/m9-chart-boundary'))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError('验收产物只能写入工作树')
    output.mkdir(parents=True, exist_ok=True)
    rows, as_of, provider, provenance = real_archive()
    evidence = {'model_quality_evaluation': False, 'source': provenance,
                'messages_and_activity': 'UI protocol fixtures', 'cases': [], 'screenshots': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        try:
            for dark, width in [(False, 1440), (True, 1440), (False, 390), (True, 390)]:
                context = browser.new_context(service_workers='block', viewport={'width': width, 'height': 960},
                    reduced_motion='reduce', is_mobile=width == 390, has_touch=width == 390)
                page = context.new_page()
                install_routes(page, dark, rows, as_of, provider)
                kline_requests = []
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                def capture(route):
                    kline_requests.append(route.request.url)
                    route.fallback()
                page.route('**/api/stock/kline/**', capture)
                page.goto(args.url + '/chat'); page.wait_for_load_state('networkidle')
                page.evaluate("async()=>{const {useStore}=await import('/src/store/useStore.ts');useStore.setState({showRightPanel:false});}")
                page.wait_for_load_state('networkidle')
                for mode in ['research', 'empty-blocks', 'legacy-inline', 'legacy-marker']:
                    page.locator('body').aria_snapshot()
                    kline_requests.clear()
                    page.evaluate(SEED, {'rows': rows, 'asOf': as_of, 'provider': provider, 'mode': mode, 'dark': dark})
                    page.wait_for_load_state('networkidle')
                    chat = page.locator('#chat-scroll-container')
                    expect(chat.get_by_role('link', name='查看引用 1')).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors, errors
                    if mode == 'research':
                        expect(chat.locator('figure.research-artifact')).to_have_count(1)
                        canvas = chat.locator('figure.research-artifact canvas')
                        expect(canvas).to_be_visible()
                        assert canvas.evaluate('(node)=>node.getContext("2d").getImageData(0,0,node.width,node.height).data.some((value,index)=>index%4===3&&value>0)')
                        assert not kline_requests, kline_requests
                    elif mode == 'empty-blocks':
                        expect(chat.locator('figure.research-artifact')).to_have_count(0)
                        expect(chat.locator('.echarts-for-react')).to_have_count(0)
                        assert not kline_requests, kline_requests
                    else:
                        assert len(kline_requests) == 1, kline_requests
                        assert '/stock/kline/AAPL?' in kline_requests[0]
                        expect(chat.locator('.echarts-for-react')).to_be_visible()
                        assert '999999' not in chat.locator('.fs-prose').inner_text()
                    filename = f"{'dark' if dark else 'light'}-{width}-{mode}.png"
                    chat.evaluate('(node)=>{node.scrollTop=0;}')
                    page.screenshot(path=str(output / filename), full_page=False)
                    evidence['screenshots'].append(filename)
                    evidence['cases'].append({'theme': 'dark' if dark else 'light', 'width': width, 'mode': mode,
                        'legacy_kline_requests': list(kline_requests), 'no_page_overflow': True})
                page.evaluate(SEED, {'rows': rows, 'asOf': as_of, 'provider': provider, 'mode': 'research', 'dark': dark})
                page.wait_for_load_state('networkidle')
                chat = page.locator('#chat-scroll-container')
                chat.locator('.turn-activity-toggle').click()
                expect(chat.locator('.turn-activity-toggle')).to_have_attribute('aria-expanded', 'true')
                expect(chat.locator('.tool-activity-row')).to_have_count(1)
                chat.locator('.turn-activity-toggle').click()
                expect(chat.locator('.tool-activity-row')).to_have_count(0)
                chat.locator('.turn-activity-toggle').click()
                chat.get_by_role('link', name='查看引用 1').click()
                expect(page.get_by_test_id('context-panel')).to_be_visible()
                focus = page.evaluate("async()=>{const {useCitationNavigation}=await import('/src/store/citationNavigation.ts');return useCitationNavigation.getState().focus;}")
                assert focus['sourceId'] == '3' and focus['runId'] == 'm9-ui-protocol', focus
                filename = f"{'dark' if dark else 'light'}-{width}-citation-focus.png"
                page.screenshot(path=str(output / filename), full_page=False)
                evidence['screenshots'].append(filename)
                context.close()
        finally:
            browser.close()
    evidence['controls'] = {'collapse_expand_activity': True, 'numeric_citation_focus': True,
        'research_artifact_no_legacy_fetch': True, 'empty_blocks_no_legacy_fetch': True,
        'legacy_inline_and_marker_fetch_preserved': True}
    (output / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'cases': len(evidence['cases']), 'controls': evidence['controls'], 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()

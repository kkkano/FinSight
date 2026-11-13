"""请求约束的统一解析：排除项和时间窗口不再由下游重新猜测。"""
from __future__ import annotations

import re
from typing import Any


_NEGATED_CLAUSE = re.compile(
    r"(?:不需要|无需|不用|不必|不要|不看|不分析|别查|排除|忽略|"
    r"\b(?:do\s+not|don't|no\s+need\s+(?:to|for)|without|exclude|skip)\b)", re.I,
)
_FACET_TERMS = {
    "news": r"新闻|消息|舆情|\bnews\b|headlines?",
    "fundamental": r"基本面|财务|\bfundamentals?\b|financials?",
    "technical": r"技术面|技术指标|\btechnicals?\b|RSI|MACD",
    "valuation": r"估值|\bvaluation\b",
    "risk": r"风险|\brisks?\b",
    "catalyst": r"催化|\bcatalysts?\b",
    "price": r"股票行情|股价|\bquotes?\b|stock\s+prices?",
}


def affirmative_query(query: str) -> tuple[str, list[str]]:
    """保留肯定任务，另存明确排除维度；不把“不要混淆”等约束当作任务。"""
    kept: list[str] = []
    excluded: list[str] = []
    for clause in re.split(r"[，,；;。！？!?]|\bbut\b|但是|但要|只需|只要", str(query or ""), flags=re.I):
        match = _NEGATED_CLAUSE.search(clause)
        if not match or re.search(r"不是不|并非不|not\s+without", clause, re.I):
            kept.append(clause)
            continue
        positive, negative = clause[:match.start()], clause[match.start():]
        if positive.strip():
            kept.append(positive)
        for name, pattern in _FACET_TERMS.items():
            if re.search(pattern, negative, re.I) and name not in excluded:
                excluded.append(name)
    return "；".join(part.strip() for part in kept if part.strip()), excluded


def parse_time_scope(query: str) -> dict[str, Any]:
    text = str(query or "")
    pattern = re.compile(
        r"(?P<direction>未来|未來|接下来|接下來|最近|过去|過去|近|next|past|last)\s*"
        r"(?P<count>\d+(?:\.\d+)?)\s*(?P<unit>小时|小時|天|日|周|週|个月|個月|hours?|days?|weeks?|months?)",
        re.I,
    )
    match = pattern.search(text)
    if match:
        count = float(match['count'])
        if count <= 0:
            return {}
        unit = match['unit'].lower()
        hours = count if unit in {'小时', '小時', 'hour', 'hours'} else count * (
            168 if unit in {'周', '週', 'week', 'weeks'} else 720 if unit in {'个月', '個月', 'month', 'months'} else 24
        )
        future = match['direction'].lower() in {'未来', '未來', '接下来', '接下來', 'next'}
        if future:
            return {'kind': 'forward', 'label': match.group(), 'days_ahead': hours / 24,
                    'direction': 'future', 'value': hours / 24, 'unit': 'days'}
        return {'kind': 'recent', 'label': match.group(), 'hours_back': hours, 'max_age_hours': hours,
                'direction': 'past', 'value': hours, 'unit': 'hours'}
    if re.search(r"(?:未来|未來|接下来|接下來).{0,5}(?:一个|一個|1)?季度|未来三个月|下季度|\bnext\s+(?:quarter|three\s+months)\b", text, re.I):
        return {'kind': 'forward', 'label': '未来一个季度', 'days_ahead': 90, 'direction': 'future', 'value': 90, 'unit': 'days'}
    return {}


def concept_without_retrieval(query: str, tickers: list[str], *, has_subject_context: bool = False) -> bool:
    """旧 frame 入口不再按问法判定概念；唯一语义 route 决定 direct。"""
    return False


def conditional_impact(query: str) -> bool:
    return bool(re.search(r'如果|假设|假如|若|\b(?:if|assuming|suppose)\b', query, re.I)
                and re.search(r'传导|影响|怎样|如何|\b(?:affect|impact|transmit|transmission)\b', query, re.I))


def build_answer_requirements(query: str, frame_id: str, render: dict, evidence: list[str], scope: dict) -> list[dict]:
    """把用户需要的回答维度冻结下来；证据不足时不能从分母里删掉。"""
    labels = {'fundamental_quality':'财务与现金流', 'valuation_reasonableness':'估值口径与依据',
              'business_model':'业务与商业模式', 'competition':'竞争格局', 'risk_level':'主要风险及依据',
              'earnings_impact':'财报对股价的影响', 'technical_quality':'技术指标与价位',
              'trend_quality':'价格趋势', 'news_catalysts':'新闻、事件及催化',
              'investment_attractiveness':'投资观点及条件', 'macro_impact':'宏观传导：区分事实与假设', 'performance':'价格或表现'}
    result = []
    dimension_evidence = {
        'fundamental_quality': ['fundamental_snapshot','filing_context'],
        'valuation_reasonableness': ['company_profile','earnings_estimates','fundamental_snapshot','price_snapshot'],
        'business_model': ['company_profile','filing_context','document_context'],
        'competition': ['document_context','filing_context','company_profile'],
        'risk_level': ['risk_profile','fundamental_snapshot'],
        'earnings_impact': ['filing_context','earnings_estimates','price_snapshot','news_context','transcript_context'],
        'technical_quality': ['technical_snapshot'], 'trend_quality': ['technical_snapshot','price_snapshot'],
        'news_catalysts': ['news_context','event_calendar'], 'macro_impact': ['macro_context','price_snapshot'],
        'performance': ['price_snapshot','performance_comparison'],
    }
    for dimension in render.get('dimensions') or []:
        analysis = dimension not in {'performance','technical_quality','trend_quality'}
        result.append({'requirement_id':f'{frame_id}:dimension:{dimension}', 'kind':'comparison' if render.get('shape')=='compare' else 'explanation' if analysis else 'fact_attribute',
                       'dimension':dimension, 'description':labels.get(dimension,dimension), 'evidence_kinds':[kind for kind in dimension_evidence.get(dimension,evidence) if kind in evidence], 'requires_analysis':analysis})
        if dimension == 'fundamental_quality':
            positive, _ = affirmative_query(query)
            components = [name for name, pattern in {
                'revenue': r'营收|收入|营业额|\brevenue\b|\bsales\b',
                'net_income': r'净利润|淨利潤|净利|\bnet\s+(?:income|profit)\b',
                'cash_flow': r'现金流|現金流|\bFCF\b|\bcash\s+flows?\b',
            }.items() if re.search(pattern, positive, re.I)]
            if components:
                result[-1]['components'] = components
    if 'macro_impact' in (render.get('dimensions') or []) and conditional_impact(query):
        targets = []
        if re.search(r'通胀|物价|\b(?:inflation|CPI|PCE)\b', query, re.I):
            targets.append(('inflation','通胀与物价'))
        if re.search(r'利率|加息|降息|\b(?:interest\s+rates?|rate\s+expectations?|Fed)\b', query, re.I):
            targets.append(('rates','利率预期'))
        sectors = re.findall(r'([^\s，,；;。？?、与和]{2,10}(?:股|行业))',query)
        if sectors:
            targets.append(('sector','、'.join(dict.fromkeys(sectors))))
        if targets:
            result = [r for r in result if r['dimension'] != 'macro_impact']
            condition = re.split(r'[，,；;。？?]',query,maxsplit=1)[0]
            for name, label in targets:
                result.append({'requirement_id':f'{frame_id}:macro:{name}', 'kind':'explanation','dimension':'macro_impact',
                               'description':f'以“{condition}”为条件，解释对{label}的传导；实际数据与假设推演分开。',
                               'evidence_kinds':['macro_context'],'requires_analysis':True,'requires_explicit_binding':True})
            if 'price_snapshot' in evidence:
                result.append({'requirement_id':f'{frame_id}:macro:price_context','kind':'fact_attribute','dimension':'performance',
                               'description':'近期价格事实或明确尚未核实；不能把条件假设写成已发生。','evidence_kinds':['price_snapshot'],'requires_analysis':False})
    if re.search(r"盘后|盘前|交易时段|after.hours|pre.market|market\s+session", query, re.I):
        result.append({'requirement_id':f'{frame_id}:quote_attributes','kind':'fact_attribute','dimension':'performance',
                       'description':'报价币种、源时间与常规/盘前/盘后属性','evidence_kinds':['price_snapshot'],
                       'requires_analysis':False,'attributes':['currency','source_timestamp','market_session']})
    if scope and ('event_calendar' in evidence or 'news_context' in evidence):
        future = scope.get('kind')=='forward'
        result.append({'requirement_id':f'{frame_id}:time_window','kind':'event_window','dimension':'news_catalysts',
                       'description':f"按{scope.get('label')}覆盖事件；确认事实与观察条件分开", 'evidence_kinds':['event_calendar'] if future else ['news_context'],
                       'requires_analysis':future,'time_window':{'direction':'future' if future else 'past','value':scope.get('days_ahead') if future else scope.get('hours_back'),'unit':'days' if future else 'hours'}})
    if re.search(r"去重|合并.*重复|同一事件|deduplicat|duplicate\s+(?:reports|events)", query, re.I):
        result.append({'requirement_id':f'{frame_id}:event_grouping','kind':'explanation','dimension':'news_catalysts',
                       'description':'同一新闻事件合并，保留出处并分开旧闻和未核实传闻','evidence_kinds':['news_context'],'requires_analysis':True})
    return result

"""既有路由回归的显式模型输出；独立于生产正则和 compiler 实现。"""
from __future__ import annotations

from copy import deepcopy

from backend.graph.semantic_requirements import SemanticRequest


def _request(query, groups, *, relation="single", scopes=None, constraints=None):
    subjects, requirements = [], []
    for index, group in enumerate(groups):
        tickers, metrics = group[:2]
        source = group[2] if len(group) > 2 else query
        subject_type = group[3] if len(group) > 3 else "company"
        subject_id = f"subject_{index}"
        if tickers is not None:
            subjects.append({"id": subject_id, "type": subject_type, "label": ", ".join(tickers) or "宏观主题", "tickers": tickers})
        for spec in metrics:
            values = {"metric": spec} if isinstance(spec, str) else dict(spec)
            metric = values["metric"]
            requirements.append({"source_text": source, "description": source, "dimension": "unknown",
                                 "kind": "comparison" if relation in {"compare", "rank"} else "explanation" if metric not in {"quote", "performance", "trend_quality", "technical_quality"} else "fact_attribute",
                                 "subject": tickers[0] if tickers and len(tickers) == 1 else None,
                                 "subject_refs": [subject_id] if tickers is not None else [],
                                 "requires_analysis": metric not in {"quote", "performance", "trend_quality", "technical_quality"},
                                 "time_scope": deepcopy((scopes or {}).get(metric, {"kind": "none"})), **values})
    return SemanticRequest.model_validate({"subjects": subjects, "relation": relation, "requirements": requirements,
                                         "constraints": constraints or []}).model_dump()


def _forward(source, days=90):
    return {"kind": "calendar_window", "count": days, "unit": "days", "direction": "future", "source_text": source}


_CATALYST = {"metric": "news_catalysts", "evidence_kinds": ["news_context", "event_calendar"]}
_FUNDAMENTAL = {"metric": "fundamental_quality", "evidence_kinds": ["company_profile", "earnings_estimates", "fundamental_snapshot", "filing_context"]}
_TECHNICAL = {"metric": "technical_quality", "evidence_kinds": ["price_snapshot", "technical_snapshot", "options_derivatives"]}
_RISK = {"metric": "risk_level", "evidence_kinds": ["price_snapshot", "risk_profile"]}
_EARNINGS = {"metric": "earnings_performance", "evidence_kinds": ["company_profile", "earnings_estimates", "fundamental_snapshot", "news_context", "event_calendar", "transcript_context", "filing_context"]}
_EARNINGS_IMPACT = {"metric": "earnings_impact", "evidence_kinds": [*_EARNINGS["evidence_kinds"], "risk_profile", "price_snapshot"]}


def fixture_for_query(query, *, state=None, seed=None):
    state, seed = state or {}, seed or {}
    ui = state.get("ui_context") or {}
    if query in {"分析影响", "总结要点", "股价分析", "分析一下"}:
        selections = ui.get("selections") or []
        if selections:
            selected = selections[0]
            kind = {"news": "news_item", "filing": "filing", "doc": "research_doc", "report": "research_doc"}[selected["type"]]
            return _request(query, [([], [{"metric": "document_summary" if query == "总结要点" else "document_question",
                                         "input_dependencies": ["source_document"]}], query, kind)])
        if query in {"分析影响", "股价分析"} and ui.get("active_symbol"):
            assert str(ui['active_symbol']).upper() == 'AAPL'
            return _request(query, [(['AAPL'], ['external_impact' if query == '分析影响' else 'trend_quality'])])
        return _request(query, [(None, [{"metric": "unknown", "metric_text": query, "input_dependencies": ["analysis_subject"]}])])
    if query in {"Compare with MSFT", "What about its PE ratio?"}:
        history = state.get('messages') or []
        contents = [item.get('content', '') if isinstance(item, dict) else getattr(item, 'content', '') for item in history]
        assert any(content in {'What is AAPL?', 'Analyze AAPL'} for content in contents), '历史绑定 fixture 必须有真实上一轮 AAPL 输入'
        return _request(query, [(['AAPL', 'MSFT'] if query == 'Compare with MSFT' else ['AAPL'],
                                 ['business_model' if query == 'Compare with MSFT' else 'valuation_reasonableness'])],
                        relation='compare' if query == 'Compare with MSFT' else 'continuation')
    catalog = {
        "Analyze AAPL": ([( ["AAPL"], ["investment_attractiveness"])], {}),
        "Analyze TSLA": ([( ["TSLA"], ["investment_attractiveness"])], {}),
        "Analyze NVDA": ([( ["NVDA"], ["investment_attractiveness"])], {}),
        "What is AAPL?": ([( ["AAPL"], ["business_model"])], {}),
        "What about TSLA?": ([( ["TSLA"], ["business_model"])], {}),
        "Tell me about MSFT": ([( ["MSFT"], ["business_model"])], {}),
        "NVDA 最新股价和技术面分析": ([( ["NVDA"], ["quote", "technical_quality"])], {}),
        "美联储利率路径对大型科技股估值有什么影响": ([( [], ["macro_impact"], query, "macro")], {}),
        "分析AAPL股价，生成投资报告": ([( ["AAPL"], ["quote", "investment_attractiveness"])], {}),
        "美国 CPI 最近走势怎么样": ([( [], ["macro_data"], query, "macro")], {}),
        "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候": ([( ["AAPL", "MSFT"], ["valuation_reasonableness"], "对比 AAPL 和 MSFT 的估值"),
            ([], ["macro_data"], "美联储下次议息是什么时候", "macro")], {"relation": "compare"}),
        "TSLA 最近的新闻对股价有什么影响": ([( ["TSLA"], ["external_impact"])], {}),
        "给我一份 NVDA 的投资分析": ([( ["NVDA"], ["investment_attractiveness"])], {}),
        "总结一下 https://example.com/a-16k-filing 的要点": ([( [], ["document_summary"], query, "research_doc")], {}),
        "帮我分析一下": ([(None, [{"metric": "unknown", "metric_text": query, "input_dependencies": ["analysis_subject"]}])], {}),
        "分析一下 英特尔 的最新基本面、技术面、催化剂与主要风险": ([( ["INTC"], [_FUNDAMENTAL, _TECHNICAL, _CATALYST, _RISK])], {}),
        "AAPL 的短线趋势、RSI、MACD 和支撑阻力怎么看？": ([( ["AAPL"], ["trend_quality", "technical_quality"])], {}),
        "你刚才提到的催化剂，未来一个季度哪些最值得跟踪？": ([( ["INTC"], [_CATALYST])], {"scopes": {"news_catalysts": _forward("未来一个季度")}}),
        "INTC 未来一个季度哪些催化剂值得跟踪？": ([( ["INTC"], [_CATALYST])], {"scopes": {"news_catalysts": _forward("未来一个季度")}}),
        "AAPL price, MSFT news, NVDA fundamentals": ([( ["AAPL"], ["quote"], "AAPL price"), (["MSFT"], ["news_catalysts"], "MSFT news"), (["NVDA"], [_FUNDAMENTAL], "NVDA fundamentals")], {}),
        "分析 AAPL 的业务模式与竞争格局": ([( ["AAPL"], ["business_model", "competition"])], {}),
        "比较 NVDA 和 AMD 的估值、增长与投资风险，哪个更适合长期研究？": ([( ["NVDA", "AMD"], ["valuation_reasonableness", _FUNDAMENTAL, _RISK])], {"relation": "rank"}),
        "先别长篇，半导体 ETF 能不能看？如果不知道就按 NVDA、AMD、TSM 这几个代表说。": ([( ["NVDA", "AMD", "TSM"], ["investment_attractiveness"])], {}),
        "NVDA 现在估值贵不贵，和增长匹配吗": ([( ["NVDA"], ["valuation_reasonableness", _FUNDAMENTAL])], {}),
        "NVDA 和 AMD 哪个估值更合理": ([( ["NVDA", "AMD"], ["valuation_reasonableness"])], {"relation": "rank"}),
        "NVDA and AMD which valuation is more reasonable": ([( ["NVDA", "AMD"], ["valuation_reasonableness"])], {"relation": "rank"}),
        "NVDA AMD TSM MSFT which valuation is more reasonable": ([( ["NVDA", "AMD", "TSM", "MSFT"], ["valuation_reasonableness"])], {"relation": "rank"}),
        "GOOGL 和 MSFT 哪个技术面更强": ([( ["GOOGL", "MSFT"], [_TECHNICAL])], {"relation": "rank"}),
        "Research whether TSLA could be affected by SpaceX": ([( ["TSLA"], ["external_impact"])], {"relation": "impact"}),
        "Check AAPL price, MSFT news, then explain Fed rate impact": ([( ["AAPL"], ["quote"], "AAPL price"), (["MSFT"], ["news_catalysts"], "MSFT news"), ([], ["macro_impact"], "explain Fed rate impact", "macro")], {}),
        "AAPL MACD technical analysis": ([( ["AAPL"], [_TECHNICAL])], {}),
        "latest news links for MSFT": ([( ["MSFT"], ["news_catalysts"])], {}),
        "AAPL price now": ([( ["AAPL"], ["quote"])], {}),
        "How did NVDA earnings affect the stock price?": ([( ["NVDA"], [_EARNINGS_IMPACT])], {}),
        "How was MSFT earnings performance?": ([( ["MSFT"], [_EARNINGS])], {}),
        "Compare AAPL and MSFT risk": ([( ["AAPL", "MSFT"], [_RISK])], {"relation": "compare"}),
        "Research AAPL institutional holdings": ([( ["AAPL"], ["holdings_ownership"])], {}),
        "分析腾讯控股（0700.HK）的最新财报、估值与主要风险。": ([( ["0700.HK"], [_EARNINGS, "valuation_reasonableness", _RISK])], {}),
        "只看 AVGO 的技术面：日线趋势、RSI、MACD、支撑和阻力，不需要新闻或基本面。": ([( ["AVGO"], ["trend_quality", "technical_quality"])], {"constraints": [
            {"constraint_type": "exclude_dimension", "source_text": "不需要新闻或基本面", "dimension": "news_catalysts"},
            {"constraint_type": "exclude_dimension", "source_text": "不需要新闻或基本面", "dimension": "fundamental_quality"}]}),
        "XOM 看近期新闻，COST 看经营基本面，BTC-USD 看价格趋势；请分别回答，不要把三种任务混在一起。": ([( ["XOM"], ["news_catalysts"], "XOM 看近期新闻"), (["COST"], [_FUNDAMENTAL], "COST 看经营基本面"), (["BTC-USD"], ["trend_quality"], "BTC-USD 看价格趋势", "crypto")], {}),
        "汇总 NFLX 最近72小时的新闻，合并同一事件的重复报道。": ([( ["NFLX"], ["news_catalysts", {"metric": "news_catalysts", "source_text": "最近72小时的新闻", "kind": "event_window"},
            {"metric": "news_catalysts", "source_text": "合并同一事件的重复报道", "kind": "explanation"}])], {"scopes": {"news_catalysts": {"kind": "calendar_window", "count": 72, "unit": "hours", "direction": "past", "source_text": "最近72小时"}}}),
        "沿用刚才这家公司，未来90天哪些已确认事件值得跟踪？": ([( ["ORCL"], [_CATALYST])], {"scopes": {"news_catalysts": _forward("未来90天")}}),
        "沿用刚才这家公司，未来90天哪些事件值得跟踪？": ([( ["ORCL"], [_CATALYST])], {"scopes": {"news_catalysts": _forward("未来90天")}}),
        "现在还值得买它吗？": ([(None, ["investment_attractiveness"])], {}),
        "为什么会跌？": ([( ["ORCL"], ["external_impact"])], {}),
        "给我一份 Salesforce（CRM）的正式投资研究报告，覆盖业务、竞争、最新财务、估值、未来90天催化和风险，关键事实附可追溯来源。": ([( ["CRM"], ["business_model", "competition", _FUNDAMENTAL, "valuation_reasonableness", _CATALYST, _RISK])], {"scopes": {"news_catalysts": _forward("未来90天")}}),
        "研究阿里巴巴港股 9988.HK 最新财务、估值和风险，只分析这个上市代码。": ([( ["9988.HK"], [_FUNDAMENTAL, "valuation_reasonableness", _RISK])], {}),
        "Visa（V）和 Mastercard（MA）谁的估值更贵、自由现金流质量更好？用可比较财期，并解释差异。": ([( ["V", "MA"], ["valuation_reasonableness", {**_FUNDAMENTAL, "components": ["cash_flow"]}])], {"relation": "rank"}),
        "如果最近原油价格走高，会怎样传导到美国通胀、利率预期与航空股？区分已发生的数据和假设推演。": ([( ["CL=F"], [
            {"metric": "macro_impact", "source_text": "美国通胀", "components": ["inflation"]},
            {"metric": "macro_impact", "source_text": "利率预期", "components": ["rates"]},
            {"metric": "macro_impact", "source_text": "航空股", "components": ["sector"]},
            {"metric": "quote", "source_text": "最近原油价格走高"}], query, "macro")], {"relation": "impact"}),
    }
    if query not in catalog:
        raise AssertionError(f"缺少显式语义模型 fixture：{query}")
    groups, kwargs = catalog[query]
    return _request(query, groups, **kwargs)
